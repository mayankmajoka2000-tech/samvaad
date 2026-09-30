"""A scripted speech engine for tests and for building the interface without models.

Each utterance returns the next line from ``texts`` (cycling). A line may carry its
language as ``"hi|मुझे तीन दिन से बुखार है।"``.
"""

from __future__ import annotations

import itertools
import threading
import time

import numpy as np

from . import ASRResult

DEFAULT_TEXTS = [
    "en|Good morning, Priya. What brings you in today?",
    "hi|मुझे तीन दिन से बुखार और खांसी है।",
    "en|Take one 500 mg tablet twice a day, after meals, for 5 days.",
    "hi|क्या मैं इसे दूध के साथ ले सकती हूँ?",
]


class MockASR:
    device = "mock"
    name = "Scripted (mock)"

    def __init__(self, texts: list[str] | None = None, delay_ms: float = 60) -> None:
        self._texts = itertools.cycle(texts or DEFAULT_TEXTS)
        self._delay = delay_ms / 1000
        self._lock = threading.Lock()
        self._current: tuple[str | None, str] | None = None

    def warmup(self) -> None:
        pass

    def _peek(self) -> tuple[str | None, str]:
        if self._current is None:
            line = next(self._texts)
            lang, _, text = line.partition("|") if "|" in line else (None, "", line)
            self._current = (lang, text)
        return self._current

    def transcribe(self, audio: np.ndarray, language: str | None = None,
                   candidates: list[str] | None = None, final: bool = True) -> ASRResult:
        start = time.perf_counter()
        with self._lock:
            time.sleep(self._delay)
            lang, text = self._peek()
            if not final:
                # A partial: reveal words in proportion to how much audio has arrived.
                words = text.split()
                shown = max(1, min(len(words), int(len(audio) / 16000 * 3)))
                return ASRResult(" ".join(words[:shown]), language or lang, (time.perf_counter() - start) * 1000)
            self._current = None
        return ASRResult(text, language or lang, (time.perf_counter() - start) * 1000)
