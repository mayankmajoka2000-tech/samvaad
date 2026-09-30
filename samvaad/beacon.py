"""Beacon events: a small queue the Arduino UNO Q polls over Wi-Fi, mirrored to the interface.

The UNO Q calls ``GET /api/beacon/poll?since=<id>`` in a loop (a long poll), so the
laptop never has to reach into the board, and no port needs opening on the UNO Q.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque

# Names whose spelling in other scripts we know. Add yours in config.toml under [beacon.aliases].
KNOWN_ALIASES = {"priya": ["प्रिया"], "rahul": ["राहुल"], "anita": ["अनीता"], "amit": ["अमित"]}


def name_heard(texts: list[str], name: str, aliases: list[str] | None = None) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    candidates = [name, *(aliases or []), *KNOWN_ALIASES.get(name.lower(), [])]
    for text in texts:
        if not text:
            continue
        for c in candidates:
            if c.isascii():
                if re.search(rf"(?<![A-Za-z]){re.escape(c)}(?![A-Za-z])", text, re.I):
                    return True
            elif c in text:
                return True
    return False


class BeaconHub:
    def __init__(self) -> None:
        self._events: deque[dict] = deque(maxlen=50)
        self._next = 1
        self._cond = asyncio.Condition()
        self.last_poll: float | None = None
        self.listeners: set = set()

    @property
    def connected(self) -> bool:
        return self.last_poll is not None and time.time() - self.last_poll < 40

    async def publish(self, kind: str, title: str, detail: str = "") -> dict:
        event = {"id": self._next, "kind": kind, "title": title, "detail": detail, "time": time.time()}
        self._next += 1
        async with self._cond:
            self._events.append(event)
            self._cond.notify_all()
        for callback in list(self.listeners):
            try:
                await callback(event)
            except Exception:  # a closed browser tab must not break the Beacon
                self.listeners.discard(callback)
        return event

    async def poll(self, since: int, timeout: float = 25.0) -> list[dict]:
        self.last_poll = time.time()

        def fresh() -> list[dict]:
            return [e for e in self._events if e["id"] > since]

        async with self._cond:
            if not fresh():
                try:
                    await asyncio.wait_for(self._cond.wait_for(lambda: bool(fresh())), timeout)
                except asyncio.TimeoutError:
                    pass
            self.last_poll = time.time()
            return fresh()

    def recent(self, n: int = 8) -> list[dict]:
        return list(self._events)[-n:]
