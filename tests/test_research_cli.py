from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sift import cli
from sift.research import loop as _loop
from sift.research import writer as _writer
from sift.research.events import Event, EventBus, EventType
from sift.research.loop import ResearcherResult


runner = CliRunner()


def _stub_loop_and_writer(monkeypatch, *, synthesis="Body [1] more [2].", sources=None):
    sources = sources or [
        {"url": "http://a/", "title": "A", "content": "ca", "similarity": 0.9},
        {"url": "http://b/", "title": "B", "content": "cb", "similarity": 0.8},
    ]
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

    monkeypatch.setattr(_loop, "run", fake_run)
    monkeypatch.setattr(_writer, "write", fake_write)
    return captured


def _env(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_HOST", "http://llm")
    monkeypatch.setenv("SIFT_LLM_MODEL", "m")
    monkeypatch.setenv("SIFT_EMBED_BASE_URL", "http://emb")
    monkeypatch.setenv("SIFT_EMBED_MODEL", "em")


def test_research_json_default(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    res = runner.invoke(cli.app, ["research", "what is X"])
    assert res.exit_code == 0, res.output
    doc = json.loads(res.stdout)
    assert doc["query"] == "what is X"
    assert doc["mode"] == "balanced"
    assert "[1]" in doc["synthesis"] and "[2]" in doc["synthesis"]
    assert {s["url"] for s in doc["sources"]} == {"http://a/", "http://b/"}
    assert doc["usage"]["total"] == 3
    assert "actions" in doc and "errors" in doc
    # action log includes the plan/search/done events
    types = [a["type"] for a in doc["actions"]]
    assert "plan" in types and "search" in types and "done" in types


def test_research_stream_ndjson(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    res = runner.invoke(cli.app, ["research", "--stream", "q"])
    assert res.exit_code == 0, res.output
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    types = {e["type"] for e in events}
    # Vane-compatible subset must be present
    assert {"init", "response", "sources", "done"}.issubset(types)


def test_research_history_file_and_system(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    captured = _stub_loop_and_writer(monkeypatch)
    hist_path = tmp_path / "h.json"
    hist_path.write_text(json.dumps([["human", "prior q"], ["assistant", "prior a"]]))
    res = runner.invoke(
        cli.app,
        ["research", "--history-file", str(hist_path), "--system", "be terse", "follow up"],
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
    res = runner.invoke(cli.app, ["research", "q"])
    assert res.exit_code != 0
    assert "embed" in res.stderr.lower()


def test_research_unknown_mode(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    res = runner.invoke(cli.app, ["research", "--mode", "bogus", "q"])
    assert res.exit_code != 0
    assert "mode" in res.stderr.lower()


def test_research_no_synthesis_exit_nonzero(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch, synthesis="")
    res = runner.invoke(cli.app, ["research", "q"])
    assert res.exit_code == 1
