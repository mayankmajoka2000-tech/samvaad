"""Engine selection on any laptop: Snapdragon NPU when available, otherwise faster-whisper + Ollama."""

import asyncio
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from samvaad import engines, platform_info
from samvaad.engines import asr_faster
from samvaad.engines.llm import AutoLLM, LLMClient, MockLLM, create_llm


# ---------------------------------------------------------------- speech engine choice

def _fake_files(tmp_path):
    enc, dec = tmp_path / "encoder.onnx", tmp_path / "decoder.onnx"
    enc.write_text("x")
    dec.write_text("x")
    return {"encoder": str(enc), "decoder": str(dec)}


def test_snapdragon_with_npu_models_prefers_the_npu(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "is_snapdragon_pc", lambda: True)
    monkeypatch.setattr(engines, "_installed", lambda m: True)
    assert engines.auto_order(_fake_files(tmp_path))[0] == "qnn"


def test_other_laptops_use_faster_whisper(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "is_snapdragon_pc", lambda: False)
    monkeypatch.setattr(engines, "_installed", lambda m: m in ("faster_whisper", "onnxruntime"))
    assert engines.auto_order(_fake_files(tmp_path)) == ["faster"]


def test_snapdragon_without_models_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "is_snapdragon_pc", lambda: True)
    monkeypatch.setattr(engines, "_installed", lambda m: True)
    order = engines.auto_order({"encoder": str(tmp_path / "missing.onnx"), "decoder": str(tmp_path / "missing2.onnx")})
    assert order[0] == "faster"


def test_auto_tries_the_next_engine_when_one_fails(monkeypatch):
    monkeypatch.setattr(engines, "auto_order", lambda cfg: ["qnn", "faster"])

    def build(name, cfg):
        if name == "qnn":
            raise RuntimeError("QNN EP not available")
        return SimpleNamespace(name="Whisper-small", device="CPU")

    monkeypatch.setattr(engines, "_build", build)
    assert engines.create_asr({"engine": "auto"}).device == "CPU"


def test_auto_with_nothing_installed_says_run_setup(monkeypatch):
    monkeypatch.setattr(engines, "auto_order", lambda cfg: [])
    with pytest.raises(ModuleNotFoundError, match="setup"):
        engines.create_asr({"engine": "auto"})


# ---------------------------------------------------------------- faster-whisper wrapper

class FakeModel:
    def __init__(self, probs):
        self.probs = probs
        self.calls = []

    def detect_language(self, audio):
        best = max(self.probs, key=self.probs.get)
        return best, self.probs[best], list(self.probs.items())

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append(language)
        detected = language or max(self.probs, key=self.probs.get)
        return iter([SimpleNamespace(text=" Take 500 mg "), SimpleNamespace(text="twice a day.")]), \
            SimpleNamespace(language=detected)


def _engine(probs):
    eng = asr_faster.FasterWhisper.__new__(asr_faster.FasterWhisper)
    eng.model, eng.name, eng.device = FakeModel(probs), "Whisper-small", "CPU"
    eng._lock = __import__("threading").Lock()
    return eng


def test_candidates_limit_language_choice():
    # Urdu scores highest (Whisper often confuses spoken Hindi and Urdu), but only en/hi are allowed.
    eng = _engine({"ur": 0.6, "hi": 0.3, "en": 0.1})
    res = eng.transcribe(np.zeros(16000, np.float32), candidates=["en", "hi"])
    assert res.language == "hi" and eng.model.calls == ["hi"]
    assert res.text == "Take 500 mg twice a day."


def test_forced_language_skips_detection():
    eng = _engine({"en": 0.9, "hi": 0.1})
    res = eng.transcribe(np.zeros(16000, np.float32), language="hi")
    assert res.language == "hi" and eng.model.calls == ["hi"]


# ---------------------------------------------------------------- translator choice

def _transport(geniex_up: bool, ollama_models: list[str] | None):
    def handler(request: httpx.Request) -> httpx.Response:
        port = request.url.port
        if port == 18181:
            if not geniex_up:
                raise httpx.ConnectError("connection refused", request=request)
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "ai-hub-models/Qwen3-4B-Instruct-2507"}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"translation": "NPU", "names": []}'}}]})
        if port == 11434:
            if ollama_models is None:
                raise httpx.ConnectError("connection refused", request=request)
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": m} for m in ollama_models]})
            if request.url.path == "/api/generate":
                return httpx.Response(200, json={"done": True})
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"translation": "नमस्ते", "names": []}'}}]})
        raise httpx.ConnectError("unknown", request=request)
    return httpx.MockTransport(handler)


def _run(coro):
    return asyncio.run(coro)


def test_auto_uses_geniex_on_the_npu_first():
    async def go():
        llm = create_llm({"engine": "auto"}, transport=_transport(True, ["qwen3:4b-instruct-2507-q4_K_M"]))
        ok = await llm.health()
        result = (ok, llm.provider, llm.device)
        await llm.close()
        return result
    assert _run(go()) == (True, "GenieX", "NPU")


def test_auto_uses_ollama_on_other_laptops():
    async def go():
        llm = create_llm({"engine": "auto"}, transport=_transport(False, ["qwen3:4b-instruct-2507-q4_K_M"]))
        ok = await llm.health()
        tr = await llm.translate("Hello", "en", "hi")
        await asyncio.sleep(0)  # let the keep-warm request run
        result = (ok, llm.provider, tr.text)
        await llm.close()
        return result
    assert _run(go()) == (True, "Ollama", "नमस्ते")


def test_ollama_without_the_model_explains_what_to_download():
    async def go():
        llm = create_llm({"engine": "auto"}, transport=_transport(False, ["llama3:8b"]))
        ok = await llm.health()
        result = (ok, llm.provider, llm.last_error)
        await llm.close()
        return result
    ok, provider, error = _run(go())
    assert not ok and provider == "Ollama" and "not downloaded" in error


def test_nothing_running_reports_offline_and_keeps_the_original_text():
    async def go():
        llm = create_llm({"engine": "auto"}, transport=_transport(False, None))
        ok = await llm.health()
        tr = await llm.translate("Take 500 mg", "en", "hi")
        await llm.close()
        return ok, tr
    ok, tr = _run(go())
    assert not ok and not tr.ok and tr.text == "Take 500 mg"


def test_create_llm_variants():
    assert isinstance(create_llm({"engine": "mock"}), MockLLM)
    assert isinstance(create_llm({"engine": "auto"}), AutoLLM)
    ollama = create_llm({"engine": "ollama"})
    assert isinstance(ollama, LLMClient) and ollama.base_url.endswith(":11434/v1")
    custom = create_llm({"engine": "openai", "base_url": "http://127.0.0.1:1234/v1", "model": "qwen3-4b"})
    assert custom.base_url == "http://127.0.0.1:1234/v1" and custom.model == "qwen3-4b"
    with pytest.raises(ValueError):
        create_llm({"engine": "nope"})


# ---------------------------------------------------------------- platform hints

def test_hints_match_the_laptop(monkeypatch):
    monkeypatch.setattr(platform_info, "is_snapdragon_pc", lambda: True)
    assert "geniex serve" in platform_info.translator_hint("m")
    monkeypatch.setattr(platform_info, "is_snapdragon_pc", lambda: False)
    monkeypatch.setattr(platform_info.platform, "system", lambda: "Darwin")
    hint = platform_info.translator_hint("qwen3:4b-instruct-2507-q4_K_M")
    assert "Ollama" in hint and "ollama pull qwen3:4b-instruct-2507-q4_K_M" in hint
    assert "setup.sh" in platform_info.setup_command()
    monkeypatch.setattr(platform_info.platform, "system", lambda: "Windows")
    assert "setup.ps1" in platform_info.setup_command()


def test_describe_reports_this_machine():
    info = platform_info.describe()
    assert info["os"] and info["arch"] and info["chip"]
