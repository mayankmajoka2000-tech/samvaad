"""Speech recognition engines.

``create_asr(config)`` returns one of:

* ``QnnWhisper``          Whisper on the Snapdragon Hexagon NPU (ONNX Runtime + QNN EP),
                          using the precompiled encoder/decoder from Qualcomm AI Hub.
* ``FasterWhisper``       Whisper on any other laptop (Windows, Mac, Linux) with faster-whisper:
                          CPU with int8 weights, or an NVIDIA GPU when present.
* ``TransformersWhisper`` Whisper through Hugging Face Transformers (needs PyTorch).
* ``MockASR``             Scripted transcripts, for tests and UI work without models.

The default engine, ``auto``, picks the NPU on a Snapdragon PC when its models are
installed, and faster-whisper everywhere else.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("samvaad")


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


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def auto_order(cfg: dict) -> list[str]:
    """Engines to try, best first, for this laptop."""
    from ..platform_info import is_snapdragon_pc

    order = []
    npu_files = Path(cfg.get("encoder", "")).exists() and Path(cfg.get("decoder", "")).exists()
    if is_snapdragon_pc() and npu_files and _installed("onnxruntime"):
        order.append("qnn")
    if _installed("faster_whisper"):
        order.append("faster")
    if _installed("torch") and _installed("transformers"):
        order.append("transformers")
    return order


def _build(engine: str, cfg: dict):
    if engine == "qnn":
        from .asr_qnn import QnnWhisper
        return QnnWhisper(cfg["encoder"], cfg["decoder"], cfg.get("model_size", "base"))
    if engine == "faster":
        from .asr_faster import FasterWhisper
        return FasterWhisper(cfg.get("cpu_model_size", "small"), cfg.get("device", "auto"),
                             int(cfg.get("threads", 0)))
    if engine == "transformers":
        from .asr_transformers import TransformersWhisper
        return TransformersWhisper(cfg.get("cpu_model_size", cfg.get("model_size", "base")))
    if engine == "mock":
        from .asr_mock import MockASR
        return MockASR(cfg.get("mock_texts"))
    raise ValueError(f"Unknown speech engine {engine!r}; use auto, qnn, faster, transformers or mock.")


def create_asr(cfg: dict):
    engine = (cfg.get("engine") or "auto").lower()
    if engine != "auto":
        return _build(engine, cfg)
    errors = []
    for candidate in auto_order(cfg):
        try:
            return _build(candidate, cfg)
        except Exception as e:  # try the next engine, and report all failures if none loads
            log.warning("Speech engine %s did not load: %s", candidate, e)
            errors.append(f"{candidate}: {e.__class__.__name__}: {e}")
    if errors:
        raise RuntimeError("No speech engine could start. " + " | ".join(errors))
    raise ModuleNotFoundError("No speech engine is installed. Run the setup script "
                              "(setup.ps1 on Windows, setup.sh on Mac/Linux).")
