from __future__ import annotations

import asyncio
import io
from pathlib import Path
from unittest.mock import MagicMock


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
            rc,
            "Console",
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


def test_followup_loop_new_triggers_on_new(monkeypatch):
    """Typing '/new' should call the on_new callback."""
    call_count = [0]

    def _input(*_):
        call_count[0] += 1
        if call_count[0] == 1:
            return "/new"
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)

    on_new_called = [False]

    def on_new():
        on_new_called[0] = True
        return None  # exit the loop

    async def run_turn(q):
        return "doc"

    session = MagicMock()
    _tui.followup_loop(run_turn, session, on_new=on_new)
    assert on_new_called[0]


def test_followup_loop_new_resets_and_runs_query(monkeypatch):
    """'/new' followed by a fresh query should run a turn with that query."""
    call_count = [0]

    def _input(*_):
        call_count[0] += 1
        if call_count[0] == 1:
            return "/new"
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)

    def on_new():
        return "fresh question"

    turn_results = []

    async def run_turn(q):
        turn_results.append(q)
        return "new doc"

    session = MagicMock()
    session.path = Path("/tmp/fresh.md")

    _tui.followup_loop(run_turn, session, on_new=on_new)
    assert turn_results == ["fresh question"]
    session.save.assert_called_once_with("new doc")


def test_followup_loop_new_no_callback(monkeypatch, capsys):
    """'/new' with no on_new callback should print a message and continue."""
    call_count = [0]

    def _input(*_):
        call_count[0] += 1
        if call_count[0] == 1:
            return "/new"
        if call_count[0] == 2:
            return "normal query"
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)

    turn_results = []

    async def run_turn(q):
        turn_results.append(q)
        return "doc"

    session = MagicMock()
    session.path = Path("/tmp/test.md")

    _tui.followup_loop(run_turn, session)
    # /new was a no-op, then normal query ran
    assert turn_results == ["normal query"]
    captured = capsys.readouterr()
    assert "/new: no reset handler available" in captured.out


def test_followup_loop_new_exact_match_only(monkeypatch):
    """'/newsomething' should be treated as a normal query, not '/new'."""
    call_count = [0]

    def _input(*_):
        call_count[0] += 1
        if call_count[0] == 1:
            return "/newsomething"
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)

    on_new_called = [False]

    def on_new():
        on_new_called[0] = True
        return None

    turn_results = []

    async def run_turn(q):
        turn_results.append(q)
        return "doc"

    session = MagicMock()
    session.path = Path("/tmp/test.md")

    _tui.followup_loop(run_turn, session, on_new=on_new)
    assert not on_new_called[0]
    assert turn_results == ["/newsomething"]
