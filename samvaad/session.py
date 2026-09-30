"""The session record: every utterance with its translation, guard result and timings.

It lives in memory while Samvaad runs. Nothing is written to disk unless the user
presses Save, and then only to the local ``sessions`` folder.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from .languages import name as lang_name


class Session:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.items: list[dict] = []
        self.started = time.time()
        self._n = 0

    def elapsed(self) -> float:
        return time.time() - self.started

    def add(self, *, kind: str, speaker: str, speaker_label: str, src: str, tgt: str | None, text: str,
            translation: str | None, guard: dict | None, names: list, timings: dict, note: str = "") -> dict:
        self._n += 1
        item = {
            "id": f"u{self._n}",
            "kind": kind,
            "speaker": speaker,
            "speaker_label": speaker_label,
            "src": src,
            "tgt": tgt,
            "text": text,
            "translation": translation,
            "names": [list(p) for p in names],
            "guard": guard,
            "t": round(self.elapsed(), 1),
            "wall": datetime.now().isoformat(timespec="seconds"),
            "timings": timings,
            "note": note,
        }
        self.items.append(item)
        return item

    def get(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def context_lines(self, n: int = 4) -> list[str]:
        return [f"{i['speaker_label']}: {i['text']}" for i in self.items[-n:]]

    def transcript_text(self, limit_chars: int = 12000) -> str:
        lines = []
        for i in self.items:
            line = f"[{i['id']}] {fmt_t(i['t'])} {i['speaker_label']} ({lang_name(i['src'])}): {i['text']}"
            if i.get("translation") and i["translation"] != i["text"]:
                line += f" | {lang_name(i['tgt'])}: {i['translation']}"
            lines.append(line)
        text = "\n".join(lines)
        return text[-limit_chars:]

    def metrics(self) -> dict:
        def stats(key: str) -> dict:
            vals = [i["timings"][key] for i in self.items if i["timings"].get(key) is not None]
            if not vals:
                return {"n": 0}
            return {"n": len(vals), "mean": round(statistics.fmean(vals)), "median": round(statistics.median(vals)),
                    "min": round(min(vals)), "max": round(max(vals))}
        return {k: stats(k) for k in ("asr_ms", "mt_ms", "end_to_end_ms", "audio_s")}

    def to_markdown(self) -> str:
        out = [f"# Samvaad session, {datetime.fromtimestamp(self.started):%d %b %Y %H:%M}", ""]
        for i in self.items:
            out.append(f"**{fmt_t(i['t'])} · {i['speaker_label']} ({lang_name(i['src'])})**  ")
            out.append(i["text"] + "  ")
            if i.get("translation") and i["translation"] != i["text"]:
                out.append(f"*{lang_name(i['tgt'])}:* {i['translation']}  ")
            if i.get("guard"):
                out.append(f"<sub>Guard: {i['guard']['message']}</sub>")
            out.append("")
        return "\n".join(out)

    def to_json(self) -> str:
        return json.dumps({"started": self.started, "items": self.items, "metrics": self.metrics()},
                          ensure_ascii=False, indent=2)

    def save(self, folder: str) -> Path:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        stem = f"session-{datetime.fromtimestamp(self.started):%Y%m%d-%H%M%S}"
        (path / f"{stem}.md").write_text(self.to_markdown(), encoding="utf-8")
        (path / f"{stem}.json").write_text(self.to_json(), encoding="utf-8")
        return path / f"{stem}.md"


def fmt_t(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60:02d}:{s % 60:02d}"
