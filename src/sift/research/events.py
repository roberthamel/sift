"""Event types and async bus shared by the researcher loop, writer, and the
three output renderers (JSON / NDJSON stream / Rich TUI)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    INIT = "init"
    PLAN = "plan"
    SEARCH = "search"
    SEARCH_RESULTS = "search_results"
    SEARCH_QUERY = "search_query"
    READING = "reading"
    FETCH_URL = "fetch_url"
    EXTRACTED = "extracted"
    RESPONSE = "response"
    SOURCES = "sources"
    ITER_PROGRESS = "iter_progress"
    DONE = "done"
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


_SENTINEL = object()


class EventBus:
    """Single-producer / multi-consumer asyncio event bus.

    `iterate()` yields until `close()` is called; `emit()` is safe to call
    from any task.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._closed = False

    def emit(self, event: Event) -> None:
        if self._closed:
            return
        self._queue.put_nowait(event)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put_nowait(_SENTINEL)

    async def iterate(self):
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            yield item
