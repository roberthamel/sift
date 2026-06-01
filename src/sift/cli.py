"""Typer entry point for `sift`."""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=False, add_completion=False)
log = logging.getLogger("sift")


@dataclass
class _Session:
    """Holds the live path and document content for a research conversation."""

    path: Path | None = None
    document: str | None = None  # full file content including frontmatter
    continuing: Path | None = None
    initial_query: str | None = None  # opening question, preserved across turns
    created: str | None = None        # ISO timestamp of first save
    turns: int = 0                    # number of completed research turns

    @property
    def body(self) -> str | None:
        """Document body with frontmatter stripped — safe to pass to the LLM."""
        if self.document is None:
            return None
        from .research import persist as _persist
        _, body = _persist.strip_frontmatter(self.document)
        return body or None

    def save(self, content: str) -> None:
        from datetime import datetime, timezone
        from .research import persist as _persist

        # Strip any frontmatter the LLM may have reproduced in its output.
        _, body = _persist.strip_frontmatter(content)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.created:
            self.created = now
        self.turns += 1

        meta = {
            "query": self.initial_query or "",
            "created": self.created,
            "updated": now,
            "turns": self.turns,
        }
        full = _persist.make_frontmatter(meta) + body
        _persist.save(self.path, full)
        self.document = full


@app.command()
def main(
    query: str | None = typer.Argument(None, help="Research question (omit to enter interactive REPL)"),
    mode: str = typer.Option("balanced", "--mode", help="speed | balanced | quality"),
    llm_host: str | None = typer.Option(None, "--llm-host", envvar="SIFT_LLM_HOST"),
    llm_apikey: str | None = typer.Option(None, "--llm-apikey", envvar="SIFT_LLM_APIKEY"),
    llm_model: str | None = typer.Option(None, "--llm-model", envvar="SIFT_LLM_MODEL"),
    embed_base_url: str | None = typer.Option(None, "--embed-base-url", envvar="SIFT_EMBED_BASE_URL"),
    embed_api_key: str | None = typer.Option(None, "--embed-api-key", envvar="SIFT_EMBED_API_KEY"),
    embed_model: str | None = typer.Option(None, "--embed-model", envvar="SIFT_EMBED_MODEL"),
    system: str | None = typer.Option(None, "--system", help="System instructions injected into the writer prompt"),
    history_file: Path | None = typer.Option(None, "--history-file", help="JSON file shaped as [[role, text], ...]"),
    stream: bool = typer.Option(False, "--stream", help="Emit NDJSON events to stdout"),
    cont: Path | None = typer.Option(None, "--continue", "-c", help="Continue an existing research document"),
    print_: bool = typer.Option(False, "--print", "-p", help="Non-interactive: print final answer to stdout and exit"),
    lang: str = typer.Option("all", "--lang"),
    safesearch: int = typer.Option(0, "--safesearch", min=0, max=2),
    allow: list[str] = typer.Option(None, "--allow"),
    block: list[str] = typer.Option(None, "--block"),
    log_file: Path | None = typer.Option(None, "--log-file"),
    verbose: bool = typer.Option(False, "--verbose"),
    settings: Path | None = typer.Option(None, "--settings"),
) -> None:
    """Research the web: plan → search → synthesize."""
    from . import bootstrap as _bootstrap

    _bootstrap.bootstrap(settings_path=settings, log_file=log_file, verbose=verbose)

    from . import llm_config
    from .research import embed_config as _embed_config

    llm_cfg = llm_config.resolve(host=llm_host, api_key=llm_apikey, model=llm_model)
    embed_cfg = _embed_config.resolve(
        host=embed_base_url, api_key=embed_api_key, model=embed_model
    )
    try:
        llm_cfg.for_llm()
        embed_cfg.for_embed()
    except llm_config.ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    if mode not in ("speed", "balanced", "quality"):
        typer.echo(f"unknown --mode: {mode}", err=True)
        raise typer.Exit(code=2)

    history: list[tuple[str, str]] = []
    if history_file is not None:
        try:
            raw = json.loads(history_file.read_text())
            for entry in raw or []:
                role, text = entry[0], entry[1]
                history.append((str(role), str(text)))
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"--history-file invalid: {exc}", err=True)
            raise typer.Exit(code=2)

    runner_kwargs = {
        "lang": lang,
        "safesearch": safesearch,
        "allow": list(allow or []) or None,
        "block": list(block or []) or None,
    }

    # Build session (preload if --continue).
    session = _Session()
    if cont is not None:
        if not cont.exists():
            typer.echo(f"--continue: file not found: {cont}", err=True)
            raise typer.Exit(code=2)
        from .research import persist as _persist_boot
        text = cont.read_text()
        meta, _ = _persist_boot.strip_frontmatter(text)
        session.path = cont
        session.document = text
        session.continuing = cont
        session.initial_query = meta.get("query") or None
        session.created = meta.get("created") or None
        session.turns = int(meta.get("turns", 0))

    # --print mode: one turn, no REPL, print answer to stdout.
    if print_:
        if query is None and cont is None:
            typer.echo("--print requires a query or --continue", err=True)
            raise typer.Exit(code=2)
        if query is None:
            # --continue + --print with no query: refresh the document.
            query = "Update and refresh this research document with latest findings."
        if not session.initial_query:
            session.initial_query = query

        import asyncio as _asyncio

        if stream:
            exit_code = _asyncio.run(
                _run_stream(
                    query=query, history=history, system=system, mode=mode,
                    llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
                    session=session,
                )
            )
        else:
            doc = _asyncio.run(
                _run_quiet(
                    query=query, history=history, system=system, mode=mode,
                    llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
                    session=session,
                )
            )
            sys.stdout.write(doc)
            if doc and not doc.endswith("\n"):
                sys.stdout.write("\n")
            exit_code = 0 if doc else 1
        raise typer.Exit(code=exit_code)

    # --stream (non-print): one-shot NDJSON, no REPL.
    if stream:
        import asyncio as _asyncio

        if query is None:
            typer.echo("--stream requires a query", err=True)
            raise typer.Exit(code=2)
        if not session.initial_query:
            session.initial_query = query
        exit_code = _asyncio.run(
            _run_stream(
                query=query, history=history, system=system, mode=mode,
                llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
                session=session,
            )
        )
        raise typer.Exit(code=exit_code)

    # Default: REPL mode.
    if query is None:
        try:
            query = input("research question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise typer.Exit(code=1)
        if not query:
            typer.echo("no query provided", err=True)
            raise typer.Exit(code=2)

    if not session.initial_query:
        session.initial_query = query

    import asyncio as _asyncio

    doc = _asyncio.run(
        _run_tui_turn(
            query=query, history=history, system=system, mode=mode,
            llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
            session=session,
        )
    )
    if doc:
        print(f"\033[2msaved → {session.path}\033[0m")

    session_history = list(history)
    session_history.append(("human", query))
    session_history.append(("assistant", doc))

    from .research import tui as _tui
    from .research.events import EventBus

    async def run_turn(q: str) -> str:
        from .research import loop as _loop
        from .research import writer as _writer

        bus = EventBus()

        async def producer():
            result = await _loop.run(
                query=q, history=session_history, system=system, mode=mode,
                llm_cfg=llm_cfg, embed_cfg=embed_cfg, bus=bus,
                runner_kwargs=runner_kwargs, document=session.body,
            )
            await _writer.write(
                query=q, history=session_history, system=system,
                sources=result.sources, mode=mode, llm_cfg=llm_cfg, bus=bus,
                existing_doc=session.body,
            )
            bus.close()

        prod = _asyncio.create_task(producer())
        updated_doc = await _tui.render_run(bus)
        await prod
        session_history.append(("human", q))
        session_history.append(("assistant", updated_doc))
        return updated_doc

    _tui.followup_loop(run_turn, session)
    raise typer.Exit(code=0)


async def _run_quiet(
    *, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs, session: _Session
) -> str:
    """Run one research turn without the TUI. Returns the full document."""
    from .research import loop as _loop
    from .research import persist as _persist
    from .research import writer as _writer
    from .research.events import EventBus

    bus = EventBus()

    if session.path is None:
        scope, slug = await _persist.pick_location(query, llm_cfg)
        session.path = _persist.resolve_path(scope, slug, continuing=session.continuing)

    result = await _loop.run(
        query=query, history=history, system=system, mode=mode,
        llm_cfg=llm_cfg, embed_cfg=embed_cfg, bus=bus, runner_kwargs=runner_kwargs,
        document=session.body,
    )
    answer = await _writer.write(
        query=query, history=history, system=system,
        sources=result.sources, mode=mode, llm_cfg=llm_cfg, bus=bus,
        existing_doc=session.body,
    )
    bus.close()

    body = (answer + _writer.format_references(result.sources, answer)) if answer else ""
    if body:
        session.save(body)
    # Return only the body for stdout (session.save wraps with frontmatter).
    return body


async def _run_stream(
    *, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs, session: _Session
) -> int:
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import persist as _persist
    from .research import writer as _writer
    from .research.events import EventBus, EventType

    if session.path is None:
        scope, slug = await _persist.pick_location(query, llm_cfg)
        session.path = _persist.resolve_path(scope, slug, continuing=session.continuing)

    bus = EventBus()
    saw_response = False
    accumulated = ""

    async def streamer():
        nonlocal saw_response, accumulated
        async for ev in bus.iterate():
            if ev.type == EventType.RESPONSE:
                saw_response = True
                accumulated += ev.data.get("delta", "")
            sys.stdout.write(json.dumps({"type": ev.type.value, "data": ev.data}, ensure_ascii=False, default=str))
            sys.stdout.write("\n")
            sys.stdout.flush()

    stream_task = _asyncio.create_task(streamer())
    result = await _loop.run(
        query=query, history=history, system=system, mode=mode,
        llm_cfg=llm_cfg, embed_cfg=embed_cfg, bus=bus, runner_kwargs=runner_kwargs,
        document=session.body,
    )
    await _writer.write(
        query=query, history=history, system=system,
        sources=result.sources, mode=mode, llm_cfg=llm_cfg, bus=bus,
        existing_doc=session.body,
    )
    bus.close()
    await stream_task

    if accumulated:
        full_doc = accumulated + _writer.format_references(result.sources, accumulated)
        session.save(full_doc)

    return 0 if saw_response else 1


async def _run_tui_turn(
    *, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs, session: _Session
) -> str:
    """Run one research turn with the TUI. Picks location and saves. Returns full doc."""
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import persist as _persist
    from .research import tui as _tui
    from .research import writer as _writer
    from .research.events import EventBus

    bus = EventBus()

    async def producer():
        if session.path is None:
            scope, slug = await _persist.pick_location(query, llm_cfg)
            session.path = _persist.resolve_path(scope, slug, continuing=session.continuing)

        result = await _loop.run(
            query=query, history=history, system=system, mode=mode,
            llm_cfg=llm_cfg, embed_cfg=embed_cfg, bus=bus, runner_kwargs=runner_kwargs,
            document=session.body,
        )
        await _writer.write(
            query=query, history=history, system=system,
            sources=result.sources, mode=mode, llm_cfg=llm_cfg, bus=bus,
            existing_doc=session.body,
        )
        bus.close()

    prod = _asyncio.create_task(producer())
    full_doc = await _tui.render_run(bus)
    await prod

    if full_doc:
        session.save(full_doc)
    return full_doc
