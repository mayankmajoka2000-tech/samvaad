"""The language model stage: translation, plain-language rewriting, Recall answers, summaries.

Talks to any OpenAI-compatible chat endpoint. On a Snapdragon PC that is the GenieX
local server running Qwen3-4B-Instruct-2507 on the Hexagon NPU
(``geniex serve`` -> http://127.0.0.1:18181/v1). On other machines, Ollama or LM
Studio work the same way for development.
"""

from __future__ import annotations

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
                 temperature: float = 0.2) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._client = httpx.AsyncClient(timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})
        self.reachable: bool | None = None
        self.last_error = ""

    @property
    def label(self) -> str:
        return self.model.split("/")[-1]

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/models", timeout=3.0)
            self.reachable = r.status_code == 200
            self.last_error = "" if self.reachable else f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            self.reachable = False
            self.last_error = str(e) or e.__class__.__name__
        return bool(self.reachable)

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
                               note="Translator unreachable; showing the original. Start GenieX (see README).")
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


def create_llm(cfg: dict):
    if (cfg.get("engine") or "openai").lower() == "mock":
        return MockLLM()
    return LLMClient(cfg.get("base_url", "http://127.0.0.1:18181/v1"),
                     cfg.get("model", "ai-hub-models/Qwen3-4B-Instruct-2507"),
                     cfg.get("api_key", "geniex"), float(cfg.get("timeout", 60)))
