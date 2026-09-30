"""End-to-end server tests with the scripted speech engine and the dictionary translator."""

import time

import numpy as np
import pytest
from starlette.testclient import TestClient

from samvaad import config
from samvaad.server import create_app

from .test_audio import silence, speechlike


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMVAAD_ASR", "mock")
    monkeypatch.setenv("SAMVAAD_LLM", "mock")
    cfg = config.load(tmp_path / "none.toml")
    cfg["session"]["save_dir"] = str(tmp_path / "sessions")
    with TestClient(create_app(cfg)) as c:
        for _ in range(50):  # wait for the (mock) speech engine to load
            if c.get("/api/status").json()["asr"]["ready"]:
                break
            time.sleep(0.05)
        yield c


def pcm(audio):
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def test_status_and_page(client):
    s = client.get("/api/status").json()
    assert s["asr"]["ready"] and s["asr"]["device"] == "mock"
    assert "hi" in s["languages"]
    assert "Samvaad" in client.get("/").text


def test_typed_line_is_translated_and_guarded(client):
    r = client.post("/api/translate", json={"text": "Take one 500 mg tablet twice a day, after meals, for 5 days.",
                                            "speaker": "a", "lang_a": "en", "lang_b": "hi"}).json()
    item = r["item"]
    assert "500 mg" in item["translation"]
    assert item["guard"]["status"] == "pass"


def test_live_audio_to_translated_item_and_beacon(client):
    with client.websocket_connect("/ws/audio") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "start", "mode": "conversation", "speaker": "auto", "lang_a": "en", "lang_b": "hi"})
        audio = np.concatenate([silence(0.6), speechlike(1.6), silence(1.2)])
        for i in range(0, len(audio), 1600):
            ws.send_bytes(pcm(audio[i:i + 1600]))
        final = None
        for _ in range(200):
            msg = ws.receive_json()
            if msg["type"] == "final":
                final = msg["item"]
                break
        assert final is not None
        assert final["text"] == "Good morning, Priya. What brings you in today?"
        assert final["speaker"] == "a" and final["tgt"] == "hi"
        assert final["guard"]["status"] == "pass"
        assert final["timings"]["asr_ms"] >= 0 and "end_to_end_ms" in final["timings"]

    events = client.get("/api/beacon/poll?since=0").json()["events"]
    assert events and events[0]["kind"] == "name"


def test_push_to_talk_flush_and_session_export(client):
    with client.websocket_connect("/ws/audio") as ws:
        ws.receive_json()
        ws.send_json({"type": "config", "mode": "conversation", "speaker": "b", "ptt": True, "lang_a": "en", "lang_b": "hi"})
        for chunk in np.array_split(np.concatenate([silence(0.4), speechlike(1.2)]), 10):
            ws.send_bytes(pcm(chunk))
        ws.send_json({"type": "flush"})
        for _ in range(200):
            msg = ws.receive_json()
            if msg["type"] == "final":
                break
        assert msg["item"]["speaker"] == "b"
    md = client.get("/api/session/export?fmt=md").text
    assert "# Samvaad session" in md
    saved = client.post("/api/session/save").json()["path"]
    assert saved.endswith(".md")
