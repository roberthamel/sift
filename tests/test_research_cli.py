from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift import cli
from sift.research import loop as _loop
from sift.research import writer as _writer
from sift.research import tui as _tui
from sift.research.events import Event, EventBus, EventType
from sift.research.loop import ResearcherResult


runner = CliRunner()

SYNTHESIS = "Body [1] more [2]."
SOURCES = [
    {"url": "http://a/", "title": "A", "content": "ca", "similarity": 0.9},
    {"url": "http://b/", "title": "B", "content": "cb", "similarity": 0.8},
]


def _stub_loop_and_writer(monkeypatch, *, synthesis=SYNTHESIS, sources=None):
    sources = sources or SOURCES
    captured = {"history": None, "system": None, "query": None}

    async def fake_run(*, query, history, system, mode, llm_cfg, embed_cfg, bus, runner_kwargs=None, client=None):
        captured["history"] = list(history) if history else []
        captured["system"] = system
        captured["query"] = query
        bus.emit(Event(EventType.INIT, {"query": query, "mode": mode}))
        bus.emit(Event(EventType.PLAN, {"plan": "x"}))
        bus.emit(Event(EventType.SEARCH, {"queries": ["q1"]}))
        bus.emit(Event(EventType.SEARCH_RESULTS, {"count": len(sources)}))
        return ResearcherResult(actions=[], sources=list(sources), usage={"prompt": 1, "completion": 2, "total": 3})

    async def fake_write(*, query, history, system, sources, mode, llm_cfg, bus, client=None):
        for piece in [synthesis[: len(synthesis) // 2], synthesis[len(synthesis) // 2 :]]:
            bus.emit(Event(EventType.RESPONSE, {"delta": piece}))
        bus.emit(Event(EventType.SOURCES, {"sources": list(sources)}))
        bus.emit(Event(EventType.DONE, {"finished": True}))
        return synthesis

    async def fake_render_run(bus, *, on_done=None):
        async for _ in bus.iterate():
            pass
        return synthesis

    monkeypatch.setattr(_loop, "run", fake_run)
    monkeypatch.setattr(_writer, "write", fake_write)
    monkeypatch.setattr(_tui, "render_run", fake_render_run)
    return captured


def _env(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_HOST", "http://llm")
    monkeypatch.setenv("SIFT_LLM_MODEL", "m")
    monkeypatch.setenv("SIFT_EMBED_BASE_URL", "http://emb")
    monkeypatch.setenv("SIFT_EMBED_MODEL", "em")


def test_research_oneshot_tui(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    res = runner.invoke(cli.app, ["what is X"])
    assert res.exit_code == 0, res.output


def test_research_oneshot_output_file(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    out = tmp_path / "answer.md"
    res = runner.invoke(cli.app, ["-o", str(out), "what is X"])
    assert res.exit_code == 0, res.output
    assert out.exists()
    assert SYNTHESIS in out.read_text()


def test_research_output_without_question_exits_2(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    out = tmp_path / "answer.md"
    res = runner.invoke(cli.app, ["-o", str(out)])
    assert res.exit_code == 2
    assert not out.exists()
    assert "question" in (res.stderr or res.output).lower()


def test_research_tui_flag_rejected(monkeypatch):
    _env(monkeypatch)
    res = runner.invoke(cli.app, ["--tui", "q"])
    assert res.exit_code != 0


def test_help_no_command_list(monkeypatch):
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0
    assert "Usage:" in res.stdout
    assert "Commands:" not in res.stdout


def test_research_stream_ndjson(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    res = runner.invoke(cli.app, ["--stream", "q"])
    assert res.exit_code == 0, res.output
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    types = {e["type"] for e in events}
    assert {"init", "response", "sources", "done"}.issubset(types)


def test_research_history_file_and_system(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    captured = _stub_loop_and_writer(monkeypatch)
    hist_path = tmp_path / "h.json"
    hist_path.write_text(json.dumps([["human", "prior q"], ["assistant", "prior a"]]))
    res = runner.invoke(
        cli.app,
        ["--history-file", str(hist_path), "--system", "be terse", "follow up"],
    )
    assert res.exit_code == 0, res.output
    assert captured["history"] == [("human", "prior q"), ("assistant", "prior a")]
    assert captured["system"] == "be terse"
    assert captured["query"] == "follow up"


def test_research_missing_embed_config(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_HOST", "http://llm")
    monkeypatch.setenv("SIFT_LLM_MODEL", "m")
    monkeypatch.delenv("SIFT_EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("SIFT_EMBED_MODEL", raising=False)
    res = runner.invoke(cli.app, ["q"])
    assert res.exit_code != 0
    assert "embed" in (res.stderr or res.output).lower()


def test_research_unknown_mode(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    res = runner.invoke(cli.app, ["--mode", "bogus", "q"])
    assert res.exit_code != 0
    assert "mode" in (res.stderr or res.output).lower()


def test_research_no_synthesis_exit_nonzero(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch, synthesis="")
    res = runner.invoke(cli.app, ["q"])
    assert res.exit_code == 1
