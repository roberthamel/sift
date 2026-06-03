from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from sift import cli
from sift.research import loop as _loop
from sift.research import writer as _writer
from sift.research import tui as _tui
from sift.research import persist as _persist
from sift.research.events import Event, EventType
from sift.research.loop import ResearcherResult


runner = CliRunner()

SYNTHESIS = "Body [1] more [2]."
SOURCES = [
    {"url": "http://a/", "title": "A", "content": "ca", "similarity": 0.9},
    {"url": "http://b/", "title": "B", "content": "cb", "similarity": 0.8},
]


def _stub_loop_and_writer(monkeypatch, *, synthesis=SYNTHESIS, sources=None):
    sources = sources or SOURCES
    captured = {
        "history": None,
        "system": None,
        "query": None,
        "existing_doc": None,
        "document": None,
    }

    async def fake_run(
        *,
        query,
        history,
        system,
        mode,
        llm_cfg,
        embed_cfg,
        bus,
        runner_kwargs=None,
        client=None,
        document=None,
    ):
        captured["history"] = list(history) if history else []
        captured["system"] = system
        captured["query"] = query
        captured["document"] = document
        bus.emit(Event(EventType.INIT, {"query": query, "mode": mode}))
        bus.emit(Event(EventType.PLAN, {"plan": "x"}))
        bus.emit(Event(EventType.SEARCH, {"queries": ["q1"]}))
        bus.emit(Event(EventType.SEARCH_RESULTS, {"count": len(sources)}))
        return ResearcherResult(
            actions=[],
            sources=list(sources),
            usage={"prompt": 1, "completion": 2, "total": 3},
        )

    async def fake_write(
        *,
        query,
        history,
        system,
        sources,
        mode,
        llm_cfg,
        bus,
        client=None,
        existing_doc=None,
    ):
        captured["existing_doc"] = existing_doc
        for piece in [
            synthesis[: len(synthesis) // 2],
            synthesis[len(synthesis) // 2 :],
        ]:
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


def _stub_persist(monkeypatch, *, scope="topic", slug="my-doc"):
    """Stub persist so no real LLM call or file write happens."""
    saved = {}

    async def fake_pick(query, llm_cfg, client=None):
        return scope, slug

    def fake_save(path, content):
        saved["path"] = path
        saved["content"] = content

    monkeypatch.setattr(_persist, "pick_location", fake_pick)
    monkeypatch.setattr(_persist, "save", fake_save)
    return saved


def _env(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_HOST", "http://llm")
    monkeypatch.setenv("SIFT_LLM_MODEL", "m")
    monkeypatch.setenv("SIFT_EMBED_BASE_URL", "http://emb")
    monkeypatch.setenv("SIFT_EMBED_MODEL", "em")


# ---------------------------------------------------------------------------
# Basic REPL / TUI mode
# ---------------------------------------------------------------------------


def test_research_oneshot_tui(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    _stub_persist(monkeypatch)
    res = runner.invoke(cli.app, ["what is X"])
    assert res.exit_code == 0, res.output


def test_research_query_arg_enters_repl_and_saves(monkeypatch, tmp_path):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    saved = _stub_persist(monkeypatch)
    # followup_loop is called after first turn; stub it to do nothing
    monkeypatch.setattr(_tui, "followup_loop", lambda run_turn, session, **kwargs: None)
    res = runner.invoke(cli.app, ["what is X"])
    assert res.exit_code == 0, res.output
    # Auto-save should have happened
    assert saved.get("path") is not None
    assert SYNTHESIS in (saved.get("content") or "")


def test_research_auto_save_includes_frontmatter(monkeypatch, tmp_path):
    """Saved documents should have YAML frontmatter with query/created/updated/turns."""
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)

    real_saved = {}

    async def fake_pick(query, llm_cfg, client=None):
        return "topic", "my-doc"

    def real_save(path, content):
        real_saved["path"] = path
        real_saved["content"] = content

    monkeypatch.setattr(_persist, "pick_location", fake_pick)
    monkeypatch.setattr(_persist, "save", real_save)
    monkeypatch.setattr(_tui, "followup_loop", lambda run_turn, session, **kwargs: None)

    res = runner.invoke(cli.app, ["what is X"])
    assert res.exit_code == 0, res.output

    content = real_saved.get("content", "")
    assert content.startswith("---\n"), "file should start with frontmatter"
    assert "queries:" in content
    assert "what is X" in content
    assert "created:" in content
    assert "updated:" in content
    assert "turns: 1" in content
    assert SYNTHESIS in content


def test_research_auto_save_path_printed(monkeypatch, capsys):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    _stub_persist(monkeypatch, scope="topic", slug="my-doc")
    monkeypatch.setattr(_tui, "followup_loop", lambda run_turn, session, **kwargs: None)
    res = runner.invoke(cli.app, ["what is X"])
    assert res.exit_code == 0
    assert "saved" in res.output
    assert "my-doc" in res.output


def test_research_no_output_flag(monkeypatch):
    _env(monkeypatch)
    res = runner.invoke(cli.app, ["-o", "out.md", "q"])
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# --print mode
# ---------------------------------------------------------------------------


def test_research_print_mode_one_shot(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    _stub_persist(monkeypatch)
    res = runner.invoke(cli.app, ["--print", "what is X"])
    assert res.exit_code == 0, res.output
    assert SYNTHESIS in res.output


def test_research_print_without_query_exits_2(monkeypatch):
    _env(monkeypatch)
    res = runner.invoke(cli.app, ["--print"])
    assert res.exit_code == 2
    assert (
        "query" in (res.stderr or res.output).lower()
        or "continue" in (res.stderr or res.output).lower()
    )


def test_research_print_no_synthesis_exit_nonzero(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch, synthesis="")
    _stub_persist(monkeypatch)
    res = runner.invoke(cli.app, ["--print", "q"])
    assert res.exit_code == 1


# ---------------------------------------------------------------------------
# --continue mode
# ---------------------------------------------------------------------------


def test_research_continue_preloads_document(monkeypatch, tmp_path):
    _env(monkeypatch)
    captured = _stub_loop_and_writer(monkeypatch)
    _stub_persist(monkeypatch)
    monkeypatch.setattr(_tui, "followup_loop", lambda run_turn, session, **kwargs: None)

    doc_file = tmp_path / "existing.md"
    doc_file.write_text("## Prior Research\n\nSome findings.")

    res = runner.invoke(cli.app, ["--continue", str(doc_file), "follow-up question"])
    assert res.exit_code == 0, res.output
    # loop.run receives the body (frontmatter stripped); the file has no frontmatter here
    assert captured["document"] == "## Prior Research\n\nSome findings."


def test_research_continue_writes_back_same_file(monkeypatch, tmp_path):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    saved = {}

    async def fake_pick(query, llm_cfg, client=None):
        return "t", "s"

    def fake_save(path, content):
        saved["path"] = path
        saved["content"] = content

    monkeypatch.setattr(_persist, "pick_location", fake_pick)
    monkeypatch.setattr(_persist, "save", fake_save)
    monkeypatch.setattr(_tui, "followup_loop", lambda run_turn, session, **kwargs: None)

    doc_file = tmp_path / "existing.md"
    doc_file.write_text("old content")

    res = runner.invoke(cli.app, ["--continue", str(doc_file), "update this"])
    assert res.exit_code == 0, res.output
    # save should target the original file, not a new one
    assert saved.get("path") == doc_file


def test_research_continue_missing_file_exits_2(monkeypatch, tmp_path):
    _env(monkeypatch)
    res = runner.invoke(cli.app, ["--continue", str(tmp_path / "nonexistent.md"), "q"])
    assert res.exit_code == 2


def test_research_print_continue_no_query_allowed(monkeypatch, tmp_path):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    _stub_persist(monkeypatch)

    doc_file = tmp_path / "doc.md"
    doc_file.write_text("# Research\n\nContent.")

    res = runner.invoke(cli.app, ["--print", "--continue", str(doc_file)])
    assert res.exit_code == 0, res.output


# ---------------------------------------------------------------------------
# --stream mode
# ---------------------------------------------------------------------------


def test_research_stream_ndjson(monkeypatch):
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch)
    _stub_persist(monkeypatch)
    res = runner.invoke(cli.app, ["--stream", "q"])
    assert res.exit_code == 0, res.output
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    types = {e["type"] for e in events}
    assert {"init", "response", "sources", "done"}.issubset(types)


def test_research_stream_without_query_exits_2(monkeypatch):
    _env(monkeypatch)
    res = runner.invoke(cli.app, ["--stream"])
    assert res.exit_code == 2


# ---------------------------------------------------------------------------
# Other existing tests
# ---------------------------------------------------------------------------


def test_research_tui_flag_rejected(monkeypatch):
    _env(monkeypatch)
    res = runner.invoke(cli.app, ["--tui", "q"])
    assert res.exit_code != 0


def test_help_no_command_list(monkeypatch):
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0
    assert "Usage:" in res.stdout
    assert "Commands:" not in res.stdout


def test_help_shows_continue_and_print(monkeypatch):
    res = runner.invoke(cli.app, ["--help"])
    assert res.exit_code == 0
    assert "--continue" in res.stdout
    assert "--print" in res.stdout


def test_help_no_output_flag(monkeypatch):
    res = runner.invoke(cli.app, ["--help"])
    assert "--output" not in res.stdout


def test_research_history_file_and_system(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    captured = _stub_loop_and_writer(monkeypatch)
    _stub_persist(monkeypatch)
    monkeypatch.setattr(_tui, "followup_loop", lambda run_turn, session, **kwargs: None)
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


def test_research_repl_continues_after_empty_synthesis(monkeypatch):
    """REPL mode should enter follow-up loop even when the first turn yields no answer."""
    _env(monkeypatch)
    _stub_loop_and_writer(monkeypatch, synthesis="")
    _stub_persist(monkeypatch)
    loop_entered = []
    monkeypatch.setattr(
        _tui,
        "followup_loop",
        lambda run_turn, session, **kwargs: loop_entered.append(True),
    )
    res = runner.invoke(cli.app, ["q"])
    assert res.exit_code == 0
    assert loop_entered, "followup_loop was not called"
