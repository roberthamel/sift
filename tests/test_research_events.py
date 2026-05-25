from __future__ import annotations

import asyncio

import pytest

from sift.research.events import Event, EventBus, EventType


def test_event_bus_emit_and_drain():
    async def main():
        bus = EventBus()
        bus.emit(Event(EventType.INIT, {"i": 0}))
        bus.emit(Event(EventType.PLAN, {"plan": "go"}))
        bus.close()
        seen = [e async for e in bus.iterate()]
        return seen

    seen = asyncio.run(main())
    assert [e.type for e in seen] == [EventType.INIT, EventType.PLAN]
    assert seen[1].data == {"plan": "go"}


def test_event_bus_close_is_idempotent():
    async def main():
        bus = EventBus()
        bus.close()
        bus.close()
        return [e async for e in bus.iterate()]

    assert asyncio.run(main()) == []


def test_event_bus_emit_after_close_is_drop():
    async def main():
        bus = EventBus()
        bus.close()
        bus.emit(Event(EventType.PLAN))
        return [e async for e in bus.iterate()]

    assert asyncio.run(main()) == []
