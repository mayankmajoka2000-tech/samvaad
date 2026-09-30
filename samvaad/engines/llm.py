"""The language model stage: translation, plain-language rewriting, Recall answers, summaries.

Talks to any OpenAI-compatible chat endpoint, running the same model, Qwen3-4B-Instruct-2507:

* Snapdragon PC: GenieX runs it on the Hexagon NPU (``geniex serve`` -> http://127.0.0.1:18181/v1).
* Any other laptop: Ollama runs it on the Apple GPU (Macs), an NVIDIA/AMD GPU or the CPU
  (http://127.0.0.1:11434/v1, model ``qwen3:4b-instruct-2507-q4_K_M``).

The default, ``auto``, uses whichever of the two is running, GenieX first.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

import httpx

from ..languages import name as lang_name

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def parse_json(text: str):
    """Tolerant JSON parse: whole reply, a fenced block, or the outermost {...}."""
    t = _THINK_RE.sub("", text or "").strip()
    t = _FENCE_RE.sub("", t).strip()
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        pass
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except ValueError:
            return None
    return None


@dataclass
class Translation:
    text: str
    names: list[tuple[str, str]] = field(default_factory=list)
    ms: float = 0.0
    ok: bool = True
    note: str = ""


class LLMClient:
    """OpenAI-compatible chat client (GenieX, Ollama, LM Studio...)."""

    def __init__(self, base_url: str, model: str, api_key: str = "geniex", timeout: float = 60.0,
                 temperature: float = 0.2, provider: str = "", device: str = "",
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.provider = provider or "OpenAI-compatible server"
        self.device = device
        self._client = httpx.AsyncClient(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"},
                                         transport=transport)
        self.reachable: bool | None = None
        self.model_missing = False
        self.last_error = ""
        self.hint = ""

    @property
    def label(self) -> str:
        name = self.model.split("/")[-1]
        if "qwen3" in name.lower() and "4b" in name.lower():
            return "Qwen3-4B"
        return name

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/models", timeout=3.0)
            self.reachable = r.status_code == 200
            self.last_error = "" if self.reachable else f"HTTP {r.status_code}"
            self.model_missing = False
            if self.reachable and self.provider == "Ollama":
                ids = {m.get("id", "") for m in (r.json().get("data") or []) if isinstance(m, dict)}
                if self.model not in ids:  # Ollama is running but the model has not been downloaded yet
                    self.reachable, self.model_missing = False, True
                    self.last_error = f"Ollama is running but {self.model} is not downloaded"
        except (httpx.HTTPError, ValueError) as e:
            self.reachable = False
            self.last_error = str(e) or e.__class__.__name__
        return bool(self.reachable)

    async def keep_warm(self, minutes: int = 30) -> None:
        """Ollama unloads a model after 5 idle minutes; ask it to keep Qwen3 in memory."""
        if self.provider != "Ollama":
            return
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            await self._client.post(f"{root}/api/generate", json={"model": self.model, "keep_alive": f"{minutes}m"},
                                    timeout=120.0)
        except httpx.HTTPError:
            pass

    async def chat(self, system: str, user: str, max_tokens: int = 400) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }
        r = await self._client.post(f"{self.base_url}/chat/completions", json=body)
        r.raise_for_status()
        self.reachable = True
        data = r.json()
        return _THINK_RE.sub("", data["choices"][0]["message"]["content"] or "").strip()

    async def translate(self, text: str, src: str, tgt: str, context: list[str] | None = None,
                        glossary: dict[str, str] | None = None) -> Translation:
        start = time.perf_counter()
        system = (
            "You are the translation stage of Samvaad, an interpreter for face-to-face conversations. "
            f"Translate what the speaker said from {lang_name(src)} into natural, spoken {lang_name(tgt)}. "
            "Rules: keep every number exactly as said, as digits wherever the source uses digits; never convert "
            "units or counting systems (keep 240 million as 240 million, keep mg); keep person and place names, "
            "transliterated into the target script when it differs; translate only, never answer or add advice. "
            'Reply with only JSON: {"translation": "...", "names": [{"source": "Priya", "target": "प्रिया"}]} '
            "with an empty names list when there are none."
        )
        parts = []
        if glossary:
            parts.append("Always translate these terms this way: " + "; ".join(f"{k} = {v}" for k, v in glossary.items()))
        if context:
            parts.append("Recent conversation, for context only:\n" + "\n".join(context[-4:]))
        parts.append("Translate this: " + json.dumps(text, ensure_ascii=False))
        try:
            reply = await self.chat(system, "\n\n".join(parts), max_tokens=400)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            self.reachable = False if isinstance(e, httpx.ConnectError) else self.reachable
            self.last_error = str(e) or e.__class__.__name__
            return Translation(text, [], (time.perf_counter() - start) * 1000, ok=False,
                               note="Translator unreachable; showing the original. Start the translator (see README).")
        data = parse_json(reply)
        if isinstance(data, dict) and isinstance(data.get("translation"), str) and data["translation"].strip():
            names = []
            for p in data.get("names") or []:
                if isinstance(p, dict) and p.get("source") and p.get("target"):
                    names.append((str(p["source"]), str(p["target"])))
            return Translation(data["translation"].strip(), names, (time.perf_counter() - start) * 1000)
        # The model ignored the format: use its text as the translation, without name checks.
        return Translation(reply.strip().strip('"'), [], (time.perf_counter() - start) * 1000)

    async def clarify(self, text: str, lang: str) -> str:
        system = (
            f"Rewrite what was said in plain, simple {lang_name(lang)} for someone who finds fast or technical "
            "speech hard to follow. Explain idioms and jargon briefly. Keep every number and name exactly. "
            "Reply with the rewrite only, in at most three short sentences."
        )
        return await self.chat(system, text, max_tokens=300)

    async def answer(self, question: str, transcript: str, lang: str) -> dict:
        system = (
            "You answer questions about a conversation transcript captured by Samvaad, an interpreter app. "
            f"Use only the transcript. Answer in {lang_name(lang)} in one or two short sentences, keeping numbers "
            "exactly as written. If the transcript does not contain the answer, say so plainly. "
            'Reply with only JSON: {"answer": "...", "cite": ["u3"]} where cite lists the ids of the lines used.'
        )
        reply = await self.chat(system, f"Transcript:\n{transcript}\n\nQuestion: {question}", max_tokens=300)
        data = parse_json(reply)
        if isinstance(data, dict) and isinstance(data.get("answer"), str):
            return {"answer": data["answer"], "cite": [str(c) for c in data.get("cite") or []]}
        return {"answer": reply, "cite": []}

    async def summarize(self, transcript: str, lang: str) -> dict:
        system = (
            f"Summarise this interpreted conversation in {lang_name(lang)}. Keep numbers, dates and names exactly. "
            'Reply with only JSON: {"summary": "two or three sentences", "actions": ["short action item", ...]}.'
        )
        reply = await self.chat(system, transcript, max_tokens=500)
        data = parse_json(reply)
        if isinstance(data, dict) and isinstance(data.get("summary"), str):
            actions = [str(a) for a in data.get("actions") or [] if str(a).strip()]
            return {"summary": data["summary"], "actions": actions}
        return {"summary": reply, "actions": []}

    async def close(self) -> None:
        await self._client.aclose()


class MockLLM:
    """Dictionary translator for tests; marks anything unknown as untranslated."""

    label = "mock"
    model = "mock"
    base_url = "mock://"
    provider = "mock"
    device = ""
    reachable = True
    last_error = ""

    PHRASES = {
        ("en", "hi", "Good morning, Priya. What brings you in today?"): ("सुप्रभात, प्रिया। आज आप किस वजह से आई हैं?", [("Priya", "प्रिया")]),
        ("hi", "en", "मुझे तीन दिन से बुखार और खांसी है।"): ("I have had a fever and a cough for three days.", []),
        ("en", "hi", "Take one 500 mg tablet twice a day, after meals, for 5 days."): ("खाने के बाद दिन में दो बार 500 mg की एक गोली लें, 5 दिन तक।", []),
        ("hi", "en", "क्या मैं इसे दूध के साथ ले सकती हूँ?"): ("Can I take it with milk?", []),
    }

    async def health(self) -> bool:
        return True

    async def translate(self, text, src, tgt, context=None, glossary=None) -> Translation:
        hit = self.PHRASES.get((src, tgt, text))
        if hit:
            return Translation(hit[0], list(hit[1]), 5.0)
        return Translation(text, [], 1.0, ok=False, note="No mock translation for this line.")

    async def clarify(self, text, lang) -> str:
        return text

    async def answer(self, question, transcript, lang) -> dict:
        return {"answer": "Mock answer.", "cite": []}

    async def summarize(self, transcript, lang) -> dict:
        return {"summary": "Mock summary.", "actions": []}

    async def close(self) -> None:
        pass


class AutoLLM:
    """Uses whichever local translator is running: GenieX (Snapdragon NPU) first, then Ollama.

    Re-checks on every ``health()`` call (the interface polls every few seconds), so starting
    Ollama or GenieX after Samvaad is fine.
    """

    def __init__(self, clients: list[LLMClient]) -> None:
        self.clients = clients
        self.active = clients[0]
        self._warmed = 0.0
        self._tasks: set = set()

    def __getattr__(self, name):  # label, model, base_url, provider, device, reachable, last_error...
        return getattr(self.active, name)

    async def health(self) -> bool:
        missing = None
        for client in self.clients:
            if await client.health():
                if client is not self.active or time.time() - self._warmed > 240:
                    self._warmed = time.time()
                    task = asyncio.get_running_loop().create_task(client.keep_warm())
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                self.active = client
                return True
            if client.model_missing:
                missing = client
        # Nothing ready: report the most useful problem (a running Ollama without the model).
        self.active = missing or self.clients[-1]
        return False

    async def translate(self, *args, **kwargs) -> Translation:
        return await self.active.translate(*args, **kwargs)

    async def clarify(self, *args, **kwargs) -> str:
        return await self.active.clarify(*args, **kwargs)

    async def answer(self, *args, **kwargs) -> dict:
        return await self.active.answer(*args, **kwargs)

    async def summarize(self, *args, **kwargs) -> dict:
        return await self.active.summarize(*args, **kwargs)

    async def chat(self, *args, **kwargs) -> str:
        return await self.active.chat(*args, **kwargs)

    async def close(self) -> None:
        for client in self.clients:
            await client.close()


GENIEX = {"base_url": "http://127.0.0.1:18181/v1", "model": "ai-hub-models/Qwen3-4B-Instruct-2507",
          "api_key": "geniex"}
OLLAMA = {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen3:4b-instruct-2507-q4_K_M", "api_key": "ollama"}


def create_llm(cfg: dict, transport: httpx.AsyncBaseTransport | None = None):
    engine = (cfg.get("engine") or "auto").lower()
    timeout = float(cfg.get("timeout", 180))
    if engine == "mock":
        return MockLLM()
    geniex = {**GENIEX, **(cfg.get("geniex") or {})}
    ollama = {**OLLAMA, **(cfg.get("ollama") or {})}

    def build(c: dict, provider: str, device: str) -> LLMClient:
        return LLMClient(c["base_url"], c["model"], c.get("api_key", "local"), timeout,
                         provider=provider, device=device, transport=transport)

    if engine == "geniex":
        return build(geniex, "GenieX", "NPU")
    if engine == "ollama":
        return build(ollama, "Ollama", "GPU/CPU")
    if engine == "openai":  # any other OpenAI-compatible server (LM Studio, llama.cpp...)
        return build({"base_url": cfg.get("base_url", OLLAMA["base_url"]), "model": cfg.get("model", OLLAMA["model"]),
                      "api_key": cfg.get("api_key", "local")}, "OpenAI-compatible server", "")
    if engine != "auto":
        raise ValueError(f"Unknown translator {engine!r}; use auto, geniex, ollama, openai or mock.")
    return AutoLLM([build(geniex, "GenieX", "NPU"), build(ollama, "Ollama", "GPU/CPU")])
