"""On a research --stream run, stdout must be pure NDJSON; nothing else may leak."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from sift import cli
from sift.research import loop as _loop
from sift.research import persist as _persist
from sift.research import writer as _writer
from sift.research import tui as _tui
from sift.research.events import Event, EventBus, EventType
from sift.research.loop import ResearcherResult


def _stub(monkeypatch):
    sources = [{"url": "http://a/", "title": "A", "content": "c", "similarity": 0.9}]

    async def fake_run(*, query, history, system, mode, llm_cfg, embed_cfg, bus, runner_kwargs=None, client=None, document=None):
        bus.emit(Event(EventType.INIT, {"query": query, "mode": mode}))
        bus.emit(Event(EventType.PLAN, {"plan": "p"}))
        bus.emit(Event(EventType.SEARCH, {"queries": ["q"]}))
        return ResearcherResult(actions=[], sources=sources, usage={"total": 1})

    async def fake_write(*, query, history, system, sources, mode, llm_cfg, bus, client=None, existing_doc=None):
        bus.emit(Event(EventType.RESPONSE, {"delta": "answer"}))
        bus.emit(Event(EventType.SOURCES, {"sources": list(sources)}))
        bus.emit(Event(EventType.DONE, {}))
        return "answer"

    async def fake_pick(query, llm_cfg, client=None):
        return "topic", "my-doc"

    monkeypatch.setattr(_loop, "run", fake_run)
    monkeypatch.setattr(_writer, "write", fake_write)
    monkeypatch.setattr(_persist, "pick_location", fake_pick)
    monkeypatch.setattr(_persist, "save", lambda path, content: None)


def test_stream_stdout_is_clean_ndjson(monkeypatch, tmp_path):
    monkeypatch.setenv("SIFT_LLM_HOST", "http://llm")
    monkeypatch.setenv("SIFT_LLM_MODEL", "m")
    monkeypatch.setenv("SIFT_EMBED_BASE_URL", "http://emb")
    monkeypatch.setenv("SIFT_EMBED_MODEL", "em")
    _stub(monkeypatch)
    log = tmp_path / "sift.log"
    r = CliRunner().invoke(cli.app, ["--stream", "--log-file", str(log), "hello"])
    assert r.exit_code == 0, r.output
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        # Every non-empty stdout line must be a valid JSON object.
        obj = json.loads(line)
        assert "type" in obj
        # No log markers leaked.
        assert " WARNING " not in line
        assert " ERROR " not in line
