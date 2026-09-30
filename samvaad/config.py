"""Settings, read from config.toml (see config.example.toml) with environment overrides."""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "server": {"host": "127.0.0.1", "port": 8765, "open_browser": True},
    "asr": {
        "engine": "qnn",
        "model_size": "base",
        "encoder": "models/whisper/encoder.onnx",
        "decoder": "models/whisper/decoder.onnx",
        "partial_interval_s": 1.2,
    },
    "llm": {
        "engine": "openai",
        "base_url": "http://127.0.0.1:18181/v1",
        "model": "ai-hub-models/Qwen3-4B-Instruct-2507",
        "api_key": "geniex",
        "timeout": 60,
    },
    "conversation": {"lang_a": "en", "lang_b": "hi", "label_a": "Doctor", "label_b": "Patient"},
    "beacon": {"name": "Priya", "side": "b"},
    "session": {"save_dir": "sessions"},
    "glossary": {},
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | os.PathLike | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    candidate = Path(path) if path else ROOT / "config.toml"
    if candidate.exists():
        with open(candidate, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    # Environment overrides, handy for tests and quick switches.
    env = os.environ
    if env.get("SAMVAAD_ASR"):
        cfg["asr"]["engine"] = env["SAMVAAD_ASR"]
    if env.get("SAMVAAD_LLM"):
        cfg["llm"]["engine"] = env["SAMVAAD_LLM"]
    if env.get("SAMVAAD_LLM_URL"):
        cfg["llm"]["base_url"] = env["SAMVAAD_LLM_URL"]
    if env.get("SAMVAAD_LLM_MODEL"):
        cfg["llm"]["model"] = env["SAMVAAD_LLM_MODEL"]
    if env.get("SAMVAAD_PORT"):
        cfg["server"]["port"] = int(env["SAMVAAD_PORT"])
    # Resolve model paths relative to the project folder.
    for key in ("encoder", "decoder"):
        p = Path(cfg["asr"][key])
        cfg["asr"][key] = str(p if p.is_absolute() else ROOT / p)
    save = Path(cfg["session"]["save_dir"])
    cfg["session"]["save_dir"] = str(save if save.is_absolute() else ROOT / save)
    return cfg
