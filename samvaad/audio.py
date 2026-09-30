"""Audio front end: utterance endpointing (voice activity) and an alarm-tone detector.

Both run on the CPU on small 20 ms frames, so the NPU only wakes up for real speech.
Audio arrives as 16 kHz mono float32 in [-1, 1].
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
FRAME = 320  # 20 ms at 16 kHz


@dataclass
class EndpointerConfig:
    start_frames: int = 4          # 80 ms of speech opens an utterance
    end_silence_ms: int = 700      # this much silence closes it
    preroll_ms: int = 300          # audio kept from before speech started
    max_utterance_s: float = 18.0  # force a cut (Whisper windows are 30 s)
    min_voiced_ms: int = 250       # utterances with less actual speech than this are ignored
    abs_threshold: float = 0.008   # RMS floor that always counts as silence
    snr_factor: float = 3.0        # speech must be this many times the noise floor


class Endpointer:
    """Splits a continuous stream into utterances with an adaptive energy threshold.

    ``feed()`` returns events: ``("start", None)``, ``("end", audio)`` where ``audio``
    is the full utterance including pre-roll.
    """

    def __init__(self, config: EndpointerConfig | None = None) -> None:
        self.cfg = config or EndpointerConfig()
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll: deque[np.ndarray] = deque(maxlen=max(1, self.cfg.preroll_ms // 20))
        self._utterance: list[np.ndarray] = []
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._voiced = 0
        self._noise = 0.004
        self.level = 0.0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def current_audio(self) -> np.ndarray:
        """The utterance so far (for partial transcripts)."""
        if not self._utterance:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._utterance)

    def speech_seconds(self) -> float:
        return sum(len(f) for f in self._utterance) / SAMPLE_RATE

    def _is_speech(self, rms: float) -> bool:
        threshold = max(self.cfg.abs_threshold, self._noise * self.cfg.snr_factor)
        return rms > threshold

    def _close(self) -> list[tuple[str, np.ndarray | None]]:
        audio = self.current_audio()
        voiced_ms = self._voiced * 20
        self._utterance = []
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._voiced = 0
        if voiced_ms < self.cfg.min_voiced_ms:
            return [("drop", None)]
        return [("end", audio)]

    def flush(self) -> list[tuple[str, np.ndarray | None]]:
        """Close the current utterance now (push-to-talk released)."""
        if self._in_speech or self._utterance:
            return self._close()
        return []

    def feed(self, samples: np.ndarray) -> list[tuple[str, np.ndarray | None]]:
        events: list[tuple[str, np.ndarray | None]] = []
        data = np.concatenate([self._pending, samples.astype(np.float32, copy=False)])
        n_frames = len(data) // FRAME
        self._pending = data[n_frames * FRAME:]
        end_frames = max(1, self.cfg.end_silence_ms // 20)
        max_samples = int(self.cfg.max_utterance_s * SAMPLE_RATE)

        for i in range(n_frames):
            frame = data[i * FRAME:(i + 1) * FRAME]
            rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
            self.level = rms
            speech = self._is_speech(rms)
            if not speech:
                # Track the noise floor only on non-speech frames (slow rise, fast fall).
                rate = 0.05 if rms > self._noise else 0.3
                self._noise += (rms - self._noise) * rate

            if not self._in_speech:
                self._preroll.append(frame)
                self._speech_run = self._speech_run + 1 if speech else 0
                if self._speech_run >= self.cfg.start_frames:
                    self._in_speech = True
                    self._silence_run = 0
                    self._voiced = self._speech_run
                    self._utterance = list(self._preroll)
                    self._preroll.clear()
                    events.append(("start", None))
            else:
                self._utterance.append(frame)
                self._silence_run = 0 if speech else self._silence_run + 1
                self._voiced += 1 if speech else 0
                total = sum(len(f) for f in self._utterance)
                if self._silence_run >= end_frames or total >= max_samples:
                    events.extend(self._close())
        return events


class AlarmDetector:
    """Flags sustained narrow-band tones in the 2.8-3.6 kHz range (typical smoke alarms).

    A deliberately simple DSP heuristic: it looks for a strong, persistent peak in
    that band over half-second windows. A learned sound classifier (YAMNet) is on
    the roadmap; this detector needs no model and costs almost nothing.
    """

    def __init__(self, low_hz: float = 2800, high_hz: float = 3600, window_s: float = 0.5,
                 ratio: float = 0.55, min_rms: float = 0.01, hits_needed: int = 3,
                 cooldown_s: float = 10.0) -> None:
        self.low_hz, self.high_hz = low_hz, high_hz
        self.window = int(window_s * SAMPLE_RATE)
        self.ratio, self.min_rms = ratio, min_rms
        self.hits_needed, self.cooldown = hits_needed, int(cooldown_s / window_s)
        self._buf = np.zeros(0, dtype=np.float32)
        self._hits = 0
        self._cool = 0
        freqs = np.fft.rfftfreq(self.window, 1 / SAMPLE_RATE)
        self._band = (freqs >= low_hz) & (freqs <= high_hz)
        self._hann = np.hanning(self.window).astype(np.float32)

    def feed(self, samples: np.ndarray) -> bool:
        self._buf = np.concatenate([self._buf, samples.astype(np.float32, copy=False)])
        fired = False
        while len(self._buf) >= self.window:
            win, self._buf = self._buf[:self.window], self._buf[self.window:]
            if self._cool > 0:
                self._cool -= 1
                continue
            rms = float(np.sqrt(np.mean(win * win)))
            spectrum = np.abs(np.fft.rfft(win * self._hann)) ** 2
            total = float(spectrum.sum()) + 1e-12
            band_ratio = float(spectrum[self._band].sum()) / total
            if rms >= self.min_rms and band_ratio >= self.ratio:
                self._hits += 1
            else:
                self._hits = max(0, self._hits - 1)
            if self._hits >= self.hits_needed:
                self._hits = 0
                self._cool = self.cooldown
                fired = True
        return fired


def int16_to_float(buf: bytes) -> np.ndarray:
    """Little-endian int16 PCM bytes -> float32 in [-1, 1]."""
    return np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0


def common_prefix_words(a: str, b: str) -> int:
    """Number of characters of ``b`` covered by the words it shares with ``a`` from the start.

    Used for LocalAgreement-style partial captions: words two consecutive passes
    agree on are shown as settled; the rest stays faint.
    """
    aw, bw = a.split(), b.split()
    n = 0
    for x, y in zip(aw, bw):
        if x != y:
            break
        n += 1
    if n == 0:
        return 0
    return len(" ".join(bw[:n]))
