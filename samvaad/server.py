"""Samvaad's local server: the web interface, the live audio pipeline, Recall and Beacon.

Everything binds to 127.0.0.1 by default: nothing leaves the laptop. Start it with
``python -m samvaad`` (or ``run.ps1``) and open http://127.0.0.1:8765.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path

import numpy as np
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__, guard
from .audio import SAMPLE_RATE, AlarmDetector, Endpointer, EndpointerConfig, common_prefix_words, int16_to_float
from .beacon import BeaconHub, name_heard
from .engines import create_asr, looks_like_hallucination
from .engines.llm import create_llm
from .languages import LANGUAGES
from .session import Session

log = logging.getLogger("samvaad")
WEB = Path(__file__).resolve().parent / "web"


class Engines:
    """Holds the speech and language engines; the speech model loads in the background."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.asr = None
        self.asr_error = ""
        self.asr_loading = True
        self.asr_lock = asyncio.Lock()
        self.llm = create_llm(cfg["llm"])
        self._llm_checked = 0.0

    async def load_asr(self) -> None:
        try:
            engine = await asyncio.to_thread(create_asr, self.cfg["asr"])
            await asyncio.to_thread(engine.warmup)
            self.asr = engine
            log.info("Speech engine ready: %s on %s", engine.name, engine.device)
        except Exception as e:  # surfaced in the interface with a fix
            self.asr_error = f"{e.__class__.__name__}: {e}"
            log.error("Speech engine failed to load: %s", self.asr_error)
        finally:
            self.asr_loading = False

    async def llm_status(self) -> dict:
        if time.time() - self._llm_checked > 5:
            self._llm_checked = time.time()
            await self.llm.health()
        return {"label": self.llm.label, "model": self.llm.model, "base_url": self.llm.base_url,
                "reachable": self.llm.reachable, "error": self.llm.last_error}

    async def transcribe(self, audio: np.ndarray, **kwargs):
        async with self.asr_lock:
            return await asyncio.to_thread(self.asr.transcribe, audio, **kwargs)


def create_app(cfg: dict) -> Starlette:
    session = Session()
    hub = BeaconHub()
    state: dict = {"engines": None, "event_sockets": set()}
    settings = {
        "lang_a": cfg["conversation"]["lang_a"], "lang_b": cfg["conversation"]["lang_b"],
        "label_a": cfg["conversation"]["label_a"], "label_b": cfg["conversation"]["label_b"],
        "beacon_name": cfg["beacon"]["name"], "beacon_side": cfg["beacon"].get("side", "b"),
        "beacon_aliases": list(cfg["beacon"].get("aliases", [])), "glossary": dict(cfg.get("glossary") or {}),
    }

    async def broadcast(message: dict) -> None:
        dead = []
        for ws in list(state["event_sockets"]):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            state["event_sockets"].discard(ws)

    async def on_beacon(event: dict) -> None:
        await broadcast({"type": "beacon", "event": event})

    hub.listeners.add(on_beacon)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        engines = Engines(cfg)
        state["engines"] = engines
        loader = asyncio.create_task(engines.load_asr())
        yield
        loader.cancel()
        await engines.llm.close()

    # ------------------------------------------------------------------ core step
    async def translate_and_record(*, text: str, src: str, tgt: str, speaker: str, kind: str,
                                   timings: dict, send=None) -> dict:
        engines: Engines = state["engines"]
        label = {"a": settings["label_a"], "b": settings["label_b"]}.get(speaker, "Captions")
        tr_text, names, note, g = text, [], "", None
        if src != tgt:
            if send:
                await send({"type": "stage", "stage": "translate"})
            tr = await engines.llm.translate(text, src, tgt, session.context_lines(), settings["glossary"])
            timings["mt_ms"] = round(tr.ms)
            tr_text, names, note = tr.text, tr.names, tr.note
            if send:
                await send({"type": "stage", "stage": "guard"})
            if tr.ok:
                g = guard.check(text, src, tr_text, tgt, names).to_dict()
        item = session.add(kind=kind, speaker=speaker, speaker_label=label, src=src, tgt=tgt, text=text,
                           translation=tr_text, guard=g, names=names, timings=timings, note=note)
        # Beacon: alert the Beacon user when someone else says their name, or on any caption.
        if kind == "caption" or speaker != settings["beacon_side"]:
            if name_heard([text, tr_text], settings["beacon_name"], settings["beacon_aliases"]):
                await hub.publish("name", f"Name heard: {settings['beacon_name']}", f"{label}, {item['id']}")
        await broadcast({"type": "item", "item": item})
        return item

    # ------------------------------------------------------------------ REST
    async def status(request: Request) -> JSONResponse:
        engines: Engines = state["engines"]
        asr = engines.asr
        return JSONResponse({
            "version": __version__,
            "asr": {"name": getattr(asr, "name", cfg["asr"]["engine"]), "device": getattr(asr, "device", ""),
                    "ready": asr is not None, "loading": engines.asr_loading, "error": engines.asr_error},
            "llm": await engines.llm_status(),
            "beacon": {"connected": hub.connected, "name": settings["beacon_name"], "recent": hub.recent()},
            "settings": settings,
            "languages": LANGUAGES,
            "session": {"items": len(session.items)},
        })

    async def translate_text(request: Request) -> JSONResponse:
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "Type something to translate."}, status_code=400)
        speaker = body.get("speaker", "a")
        lang_a, lang_b = body.get("lang_a", settings["lang_a"]), body.get("lang_b", settings["lang_b"])
        src, tgt = (lang_a, lang_b) if speaker == "a" else (lang_b, lang_a)
        start = time.perf_counter()
        timings = {"asr_ms": None, "audio_s": None}
        item = await translate_and_record(text=text, src=src, tgt=tgt, speaker=speaker, kind="typed", timings=timings)
        item["timings"]["end_to_end_ms"] = round((time.perf_counter() - start) * 1000)
        return JSONResponse({"item": item})

    async def ask(request: Request) -> JSONResponse:
        body = await request.json()
        question, lang = (body.get("question") or "").strip(), body.get("lang", "en")
        if not question:
            return JSONResponse({"error": "Type a question."}, status_code=400)
        if not session.items:
            return JSONResponse({"answer": "Nothing has been said in this session yet.", "cite": [], "unsupported": []})
        engines: Engines = state["engines"]
        try:
            result = await engines.llm.answer(question, session.transcript_text(), lang)
        except Exception as e:
            return JSONResponse({"answer": None, "cite": keyword_search(question), "unsupported": [],
                                 "note": f"Translator unreachable ({e.__class__.__name__}); showing the closest moments."})
        cites = [c for c in result["cite"] if session.get(c)]
        sources = []
        for c in cites:
            it = session.get(c)
            sources += [(it["text"], it["src"]), (it.get("translation") or "", it.get("tgt") or it["src"])]
        unsupported = guard.numbers_supported(result["answer"], lang, sources) if cites else []
        return JSONResponse({"answer": result["answer"], "cite": cites, "unsupported": unsupported})

    def keyword_search(question: str) -> list[str]:
        words = {w for w in question.lower().split() if len(w) > 3}
        scored = []
        for it in session.items:
            hay = f"{it['text']} {it.get('translation') or ''}".lower()
            score = sum(1 for w in words if w[:5] in hay)
            if score:
                scored.append((score, it["id"]))
        return [i for _, i in sorted(scored, reverse=True)[:2]]

    async def summary(request: Request) -> JSONResponse:
        body = await request.json()
        if not session.items:
            return JSONResponse({"summary": "Nothing has been said in this session yet.", "actions": []})
        try:
            return JSONResponse(await state["engines"].llm.summarize(session.transcript_text(), body.get("lang", "en")))
        except Exception as e:
            return JSONResponse({"error": f"The language model is unreachable ({e.__class__.__name__}). Start GenieX."}, status_code=503)

    async def clarify(request: Request) -> JSONResponse:
        body = await request.json()
        item = session.get(body.get("id", ""))
        if not item:
            return JSONResponse({"error": "That line is no longer in the session."}, status_code=404)
        lang = body.get("lang") or item.get("tgt") or item["src"]
        source = item.get("translation") if lang == item.get("tgt") else item["text"]
        try:
            text = await state["engines"].llm.clarify(source or item["text"], lang)
        except Exception as e:
            return JSONResponse({"error": f"The language model is unreachable ({e.__class__.__name__}). Start GenieX."}, status_code=503)
        return JSONResponse({"id": item["id"], "lang": lang, "text": text})

    async def get_session(request: Request) -> JSONResponse:
        return JSONResponse({"items": session.items, "metrics": session.metrics()})

    async def reset_session(request: Request) -> JSONResponse:
        session.reset()
        await broadcast({"type": "reset"})
        return JSONResponse({"ok": True})

    async def export_session(request: Request) -> Response:
        fmt = request.query_params.get("fmt", "md")
        if fmt == "json":
            return Response(session.to_json(), media_type="application/json",
                            headers={"Content-Disposition": 'attachment; filename="samvaad-session.json"'})
        return Response(session.to_markdown(), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="samvaad-session.md"'})

    async def save_session(request: Request) -> JSONResponse:
        path = session.save(cfg["session"]["save_dir"])
        return JSONResponse({"path": str(path)})

    async def metrics(request: Request) -> JSONResponse:
        return JSONResponse(session.metrics())

    async def update_settings(request: Request) -> JSONResponse:
        body = await request.json()
        for key in ("lang_a", "lang_b", "label_a", "label_b", "beacon_name", "beacon_side"):
            if isinstance(body.get(key), str):
                settings[key] = body[key].strip()
        if isinstance(body.get("glossary"), dict):
            settings["glossary"] = {str(k): str(v) for k, v in body["glossary"].items() if str(k).strip()}
        return JSONResponse({"settings": settings})

    async def beacon_poll(request: Request) -> JSONResponse:
        since = int(request.query_params.get("since", "0") or 0)
        return JSONResponse({"events": await hub.poll(since)})

    async def beacon_test(request: Request) -> JSONResponse:
        event = await hub.publish("test", "Test alert", "Sent from the laptop")
        return JSONResponse({"event": event, "connected": hub.connected})

    # ------------------------------------------------------------------ WebSockets
    async def events_ws(ws: WebSocket) -> None:
        await ws.accept()
        state["event_sockets"].add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            state["event_sockets"].discard(ws)

    async def audio_ws(ws: WebSocket) -> None:
        await ws.accept()
        engines: Engines = state["engines"]
        conf = {"mode": "conversation", "speaker": "auto", "src": "auto", "tgt": "en", "ptt": False}
        endpointer = Endpointer()
        alarm = AlarmDetector()
        paused = False
        last_level = 0.0
        last_partial = 0.0
        prev_partial = ""
        partial_task: asyncio.Task | None = None
        finals: asyncio.Queue = asyncio.Queue()
        send_lock = asyncio.Lock()
        interval = float(cfg["asr"].get("partial_interval_s", 1.2))

        async def send(msg: dict) -> None:
            async with send_lock:
                with contextlib.suppress(Exception):
                    await ws.send_json(msg)

        def asr_language() -> tuple[str | None, list[str] | None]:
            if conf["mode"] == "captions":
                return (None if conf["src"] == "auto" else conf["src"]), None
            if conf["speaker"] in ("a", "b"):
                return settings["lang_" + conf["speaker"]], None
            return None, [settings["lang_a"], settings["lang_b"]]

        async def finalize(audio: np.ndarray, detected_at: float, speaker_hint: str) -> None:
            nonlocal prev_partial
            if engines.asr is None:
                await send({"type": "error", "message": engines.asr_error or "The speech model is still loading."})
                return
            await send({"type": "stage", "stage": "recognise"})
            forced, candidates = asr_language()
            res = await engines.transcribe(audio, language=forced, candidates=candidates, final=True)
            seconds = len(audio) / SAMPLE_RATE
            prev_partial = ""
            if looks_like_hallucination(res.text, seconds):
                await send({"type": "partial", "text": "", "stable": 0, "speaker": speaker_hint})
                await send({"type": "stage", "stage": None})
                return
            timings = {"asr_ms": round(res.ms), "audio_s": round(seconds, 2)}
            if conf["mode"] == "captions":
                src = res.language or forced or "en"
                item = await translate_and_record(text=res.text, src=src, tgt=conf["tgt"], speaker="captions",
                                                  kind="caption", timings=timings, send=send)
            else:
                speaker = speaker_hint
                if speaker not in ("a", "b"):
                    speaker = "b" if res.language == settings["lang_b"] and settings["lang_a"] != settings["lang_b"] else "a"
                src = settings["lang_" + speaker]
                tgt = settings["lang_" + ("b" if speaker == "a" else "a")]
                item = await translate_and_record(text=res.text, src=src, tgt=tgt, speaker=speaker,
                                                  kind="speech", timings=timings, send=send)
            item["timings"]["end_to_end_ms"] = round((time.perf_counter() - detected_at) * 1000)
            await send({"type": "final", "item": item})
            await send({"type": "stage", "stage": None})

        async def final_worker() -> None:
            while True:
                audio, detected_at, speaker = await finals.get()
                try:
                    await finalize(audio, detected_at, speaker)
                except Exception as e:
                    log.exception("Processing an utterance failed")
                    await send({"type": "error", "message": f"Could not process that utterance: {e}"})
                    await send({"type": "stage", "stage": None})

        async def run_partial() -> None:
            nonlocal prev_partial
            audio = endpointer.current_audio()
            if engines.asr is None or len(audio) < 0.8 * SAMPLE_RATE or engines.asr_lock.locked():
                return
            forced, candidates = asr_language()
            res = await engines.transcribe(audio[-30 * SAMPLE_RATE:], language=forced, candidates=candidates, final=False)
            if not endpointer.in_speech:
                return  # the utterance ended meanwhile; the final result is on its way
            stable = common_prefix_words(prev_partial, res.text)
            prev_partial = res.text
            await send({"type": "partial", "text": res.text, "stable": stable, "speaker": conf["speaker"],
                        "asr_ms": round(res.ms)})

        def handle_events(events) -> None:
            for kind, audio in events:
                if kind == "start":
                    asyncio.create_task(send({"type": "vad", "speech": True}))
                    asyncio.create_task(send({"type": "stage", "stage": "capture"}))
                elif kind == "end":
                    asyncio.create_task(send({"type": "vad", "speech": False}))
                    finals.put_nowait((audio, time.perf_counter(), conf["speaker"]))
                elif kind == "drop":
                    asyncio.create_task(send({"type": "vad", "speech": False}))
                    asyncio.create_task(send({"type": "stage", "stage": None}))

        worker = asyncio.create_task(final_worker())
        await send({"type": "ready", "asr": getattr(engines.asr, "name", None), "loading": engines.asr_loading,
                    "error": engines.asr_error})
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if paused:
                        continue
                    samples = int16_to_float(msg["bytes"])
                    handle_events(endpointer.feed(samples))
                    if alarm.feed(samples):
                        await hub.publish("alarm", "Alarm-like sound", "Strong 3 kHz tone for over a second")
                        await send({"type": "alarm"})
                    now = time.perf_counter()
                    if now - last_level > 0.1:
                        last_level = now
                        await send({"type": "level", "v": round(endpointer.level, 4)})
                    if (interval > 0 and endpointer.in_speech and now - last_partial > interval
                            and (partial_task is None or partial_task.done())):
                        last_partial = now
                        partial_task = asyncio.create_task(run_partial())
                elif msg.get("text"):
                    data = json.loads(msg["text"])
                    kind = data.get("type")
                    if kind in ("start", "config"):
                        for key in ("mode", "speaker", "src", "tgt"):
                            if isinstance(data.get(key), str):
                                conf[key] = data[key]
                        if "ptt" in data:
                            conf["ptt"] = bool(data["ptt"])
                            endpointer.cfg = EndpointerConfig(end_silence_ms=2500 if conf["ptt"] else 700)
                        for key in ("lang_a", "lang_b"):
                            if isinstance(data.get(key), str):
                                settings[key] = data[key]
                    elif kind == "flush":
                        handle_events(endpointer.flush())
                    elif kind == "pause":
                        paused = True
                        endpointer.flush()  # discard anything half-heard while Samvaad speaks
                    elif kind == "resume":
                        paused = False
        except WebSocketDisconnect:
            pass
        finally:
            worker.cancel()
            if partial_task:
                partial_task.cancel()

    routes = [
        Route("/api/status", status),
        Route("/api/translate", translate_text, methods=["POST"]),
        Route("/api/ask", ask, methods=["POST"]),
        Route("/api/summary", summary, methods=["POST"]),
        Route("/api/clarify", clarify, methods=["POST"]),
        Route("/api/session", get_session),
        Route("/api/session/reset", reset_session, methods=["POST"]),
        Route("/api/session/export", export_session),
        Route("/api/session/save", save_session, methods=["POST"]),
        Route("/api/metrics", metrics),
        Route("/api/settings", update_settings, methods=["POST"]),
        Route("/api/beacon/poll", beacon_poll),
        Route("/api/beacon/test", beacon_test, methods=["POST"]),
        WebSocketRoute("/ws/audio", audio_ws),
        WebSocketRoute("/ws/events", events_ws),
        Mount("/", app=StaticFiles(directory=str(WEB), html=True), name="web"),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.session = session
    app.state.hub = hub
    app.state.settings = settings
    return app
