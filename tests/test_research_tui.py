from __future__ import annotations

import asyncio
import io
from pathlib import Path
from unittest.mock import MagicMock

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


def test_followup_loop_blank_line_reprompts(monkeypatch, capsys):
    """Blank line should re-prompt, not exit."""
    inputs = iter(["", ""])

    def _input(*_):
        try:
            val = next(inputs)
            if val == "":
                return ""
            return val
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", _input)

    calls = []

    async def run_turn(q):
        calls.append(q)
        return "doc"

    session = MagicMock()
    session.path = Path("/tmp/test.md")

    _tui.followup_loop(run_turn, session)
    # Both inputs were blank → re-prompted each time → EOF raised → exit
    assert calls == []


def test_followup_loop_exits_on_eof(monkeypatch):
    def _raise(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)

    async def run_turn(q):
        return "doc"

    session = MagicMock()
    _tui.followup_loop(run_turn, session)


def test_followup_loop_saves_and_prints_path(monkeypatch, capsys):
    """Each turn should call session.save and print 'saved → <path>'."""
    call_count = [0]

    def _input(*_):
        call_count[0] += 1
        if call_count[0] == 1:
            return "follow-up question"
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)

    turn_results = []

    async def run_turn(q):
        turn_results.append(q)
        return "updated document"

    session = MagicMock()
    session.path = Path(".ai/research/topic/doc.md")

    _tui.followup_loop(run_turn, session)

    assert turn_results == ["follow-up question"]
    session.save.assert_called_once_with("updated document")
    captured = capsys.readouterr()
    assert "saved" in captured.out
    assert str(session.path) in captured.out


def test_followup_loop_no_w_command(monkeypatch):
    """The 'w' input should be treated as a research query, not a write command."""
    call_count = [0]

    def _input(*_):
        call_count[0] += 1
        if call_count[0] == 1:
            return "w"
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)

    queries = []

    async def run_turn(q):
        queries.append(q)
        return "result"

    session = MagicMock()
    session.path = Path("/tmp/x.md")

    _tui.followup_loop(run_turn, session)
    assert queries == ["w"]
