"""Whisper on any laptop with faster-whisper (CTranslate2).

Runs on Windows (Intel/AMD), macOS (Apple Silicon and Intel) and Linux, on the CPU with
int8 weights, or on an NVIDIA GPU when one is present. No PyTorch needed. The model is
downloaded once from Hugging Face (Systran/faster-whisper-<size>) and then works offline.
"""

from __future__ import annotations

import os
import threading
import time

import numpy as np

from . import ASRResult


def _load(model_size: str, device: str, compute_type: str, threads: int):
    from faster_whisper import WhisperModel

    try:  # offline first, so a laptop with Wi-Fi off starts instantly from the cache
        return WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=threads,
                            local_files_only=True)
    except Exception:
        return WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=threads)


class FasterWhisper:
    def __init__(self, model_size: str = "small", device: str = "auto", threads: int = 0) -> None:
        import ctranslate2

        self.model_size = model_size
        self.threads = threads or max(2, min(8, os.cpu_count() or 4))
        self._lock = threading.Lock()
        self.model = None
        want_gpu = device in ("auto", "cuda")
        if want_gpu and _cuda_devices(ctranslate2) > 0:
            try:
                self.model = _load(model_size, "cuda", "float16", self.threads)
                self.model.detect_language(audio=np.zeros(16000, dtype=np.float32))  # fails fast without cuDNN
                self.device = "GPU"
            except Exception:
                self.model = None
        if self.model is None:
            self.model = _load(model_size, "cpu", "int8", self.threads)
            self.device = "CPU"
        self.name = f"Whisper-{model_size}"

    def warmup(self) -> None:
        self.transcribe(np.zeros(16000, dtype=np.float32), "en")

    def pick_language(self, audio: np.ndarray, candidates: list[str]) -> tuple[str, dict]:
        """Most likely language among the two speakers' languages (hands-free Conversation mode)."""
        _, _, probs = self.model.detect_language(audio=audio)
        table = dict(probs)
        best = max(candidates, key=lambda code: table.get(code, 0.0))
        return best, table

    def transcribe(self, audio: np.ndarray, language: str | None = None,
                   candidates: list[str] | None = None, final: bool = True) -> ASRResult:
        start = time.perf_counter()
        audio = np.asarray(audio, dtype=np.float32)
        with self._lock:
            lang = language
            if not lang and candidates:
                lang, _ = self.pick_language(audio, candidates)
            segments, info = self.model.transcribe(
                audio, language=lang, task="transcribe", beam_size=1, temperature=0.0,
                without_timestamps=True, condition_on_previous_text=False, vad_filter=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        return ASRResult(text, lang or info.language, (time.perf_counter() - start) * 1000)


def _cuda_devices(ctranslate2) -> int:
    try:
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0
