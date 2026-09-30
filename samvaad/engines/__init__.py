"""Speech recognition engines.

``create_asr(config)`` returns one of:

* ``QnnWhisper``          Whisper on the Snapdragon Hexagon NPU (ONNX Runtime + QNN EP),
                          using the precompiled encoder/decoder from Qualcomm AI Hub.
* ``TransformersWhisper`` Whisper on the CPU through Hugging Face Transformers (fallback
                          for machines without a Snapdragon NPU; needs PyTorch).
* ``MockASR``             Scripted transcripts, for tests and UI work without models.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ASRResult:
    text: str
    language: str | None
    ms: float = 0.0


# Short outputs Whisper is known to produce on near-silence; dropped when the clip is short.
HALLUCINATIONS = {
    "", "you", "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
    "bye.", "bye", ".", "...", "okay.", "so", "uh", "um",
}


def looks_like_hallucination(text: str, seconds: float) -> bool:
    t = text.strip().lower()
    if not t:
        return True
    return seconds < 1.2 and t in HALLUCINATIONS


def create_asr(cfg: dict):
    engine = (cfg.get("engine") or "qnn").lower()
    if engine == "qnn":
        from .asr_qnn import QnnWhisper
        return QnnWhisper(cfg["encoder"], cfg["decoder"], cfg.get("model_size", "base"))
    if engine == "transformers":
        from .asr_transformers import TransformersWhisper
        return TransformersWhisper(cfg.get("model_size", "base"))
    if engine == "mock":
        from .asr_mock import MockASR
        return MockASR(cfg.get("mock_texts"))
    raise ValueError(f"Unknown ASR engine {engine!r}; use qnn, transformers or mock.")
