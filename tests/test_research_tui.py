from __future__ import annotations

import asyncio
import io

import pytest

from sift.research import tui as _tui
from sift.research.events import Event, EventBus, EventType


def test_render_run_collects_response_deltas(monkeypatch):
    """Smoke test: render_run accumulates response deltas into the returned
    synthesis even when Rich is asked not to render to a tty."""

    async def main():
        bus = EventBus()

        async def produce():
            bus.emit(Event(EventType.INIT))
            bus.emit(Event(EventType.PLAN, {"plan": "go"}))
            bus.emit(Event(EventType.RESPONSE, {"delta": "Hello "}))
            bus.emit(Event(EventType.RESPONSE, {"delta": "world."}))
            bus.emit(Event(EventType.SOURCES, {"sources": []}))
            bus.emit(Event(EventType.DONE, {}))
            bus.close()

        # Force Rich onto a string buffer so the test does not need a real tty.
        import rich.console as rc

        real_console = rc.Console
        monkeypatch.setattr(
            rc, "Console",
            lambda *a, **kw: real_console(file=io.StringIO(), force_terminal=False),
        )

        task = asyncio.create_task(produce())
        out = await _tui.render_run(bus)
        await task
        return out

    out = asyncio.run(main())
    assert out == "Hello world."


def test_followup_loop_exits_on_blank(monkeypatch, capsys):
    inputs = iter([""])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    calls = []

    async def runner(q, hist):
        calls.append((q, list(hist)))
        return "ans"

    _tui.followup_loop(runner, [])
    assert calls == []


def test_followup_loop_exits_on_eof(monkeypatch):
    def _raise(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)

    async def runner(q, hist):
        return "ans"

    _tui.followup_loop(runner, [])
