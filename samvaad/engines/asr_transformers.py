"""Whisper on the CPU via Hugging Face Transformers.

A fallback for development machines without a Snapdragon NPU. Slower, but the rest
of Samvaad works the same. Install PyTorch first (``pip install torch``).
"""

from __future__ import annotations

import re
import threading
import time

import numpy as np

from . import ASRResult

_LANG_RE = re.compile(r"<\|([a-z]{2,3})\|>")


class TransformersWhisper:
    device = "CPU"

    def __init__(self, model_size: str = "base") -> None:
        import torch  # noqa: F401  (fails early with a clear error if PyTorch is missing)
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        hf_id = f"openai/whisper-{model_size}"
        self.name = f"Whisper-{model_size} (CPU)"
        self.processor = WhisperProcessor.from_pretrained(hf_id)
        self.model = WhisperForConditionalGeneration.from_pretrained(hf_id)
        self.model.eval()
        self._lock = threading.Lock()

    def warmup(self) -> None:
        self.transcribe(np.zeros(16000, dtype=np.float32), "en")

    def transcribe(self, audio: np.ndarray, language: str | None = None,
                   candidates: list[str] | None = None, final: bool = True) -> ASRResult:
        import torch

        start = time.perf_counter()
        feats = self.processor(audio, sampling_rate=16000, return_tensors="pt").input_features
        kwargs = {"task": "transcribe", "max_new_tokens": 200}
        if language:
            kwargs["language"] = language
        with self._lock, torch.no_grad():
            ids = self.model.generate(feats, **kwargs)
        raw = self.processor.batch_decode(ids, skip_special_tokens=False)[0]
        text = self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        found = _LANG_RE.findall(raw)
        detected = found[0] if found else None
        if candidates and detected not in candidates:
            detected = candidates[0]
        return ASRResult(text, language or detected, (time.perf_counter() - start) * 1000)
