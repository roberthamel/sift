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


def _open_in_editor(path: Path) -> bool:
    """Open *path* in $EDITOR/$VISUAL. Returns False if none is configured."""
    import os
    import subprocess

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        return False
    subprocess.run([*editor.split(), str(path)], check=False)
    return True


def _run_config(spec: str | None, *, init: bool, edit: bool, force: bool) -> int:
    """Handle the `--config` family of operations. Returns a process exit code.

    Dispatch on the combination of flags and the optional ``spec`` positional:
    - ``--init``           → write template, open $EDITOR (``--force`` to overwrite)
    - ``--edit``           → open existing file in $EDITOR
    - ``key=value``        → set a value
    - ``key``              → get the resolved value
    - (nothing)            → show the effective configuration
    """
    from . import config_file as _cf

    path = _cf.config_path()

    if init and edit:
        typer.echo("--init and --edit are mutually exclusive", err=True)
        return 2

    if init:
        if path.exists() and not force:
            typer.echo(
                f"config file already exists: {path}\n"
                "Pass --force to overwrite.",
                err=True,
            )
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_cf.template_text())
        if not _open_in_editor(path):
            typer.echo(f"wrote {path} ($EDITOR not set — edit it manually)")
        return 0

    if edit:
        if not path.exists():
            typer.echo(
                f"no config file at {path}\nRun `sift --config --init` first.", err=True
            )
            return 1
        if not _open_in_editor(path):
            typer.echo(f"$EDITOR not set — config file is at {path}", err=True)
            return 1
        return 0

    if spec is not None:
        key, sep, value = spec.partition("=")
        key = key.strip()
        if key not in _cf.KEYS:
            typer.echo(f"unknown config key: {key}", err=True)
            return 2
        if sep:  # key=value → set, key= (empty) → clear
            if value == "":
                saved = _cf.unset(key)
                typer.echo(f"cleared {key} in {saved}")
                return 0
            saved = _cf.set(key, value)
            typer.echo(f"set {key} in {saved}")
            return 0
        # bare key → get resolved value
        resolved, _ = _cf.resolve_value(key)
        if resolved is None:
            return 1
        typer.echo(resolved)
        return 0

    # No spec, no flags → show effective configuration.
    typer.echo(f"config file: {path}{'' if path.exists() else ' (not created)'}")
    typer.echo("")
    for key, key_spec in _cf.KEYS.items():
        value, source = _cf.resolve_value(key)
        shown = (
            "(unset)"
            if value is None
            else (_cf.mask(value) if key_spec.secret else value)
        )
        typer.echo(f"  {key:<16} {shown:<28} [{source}]")
    return 0


@dataclass
class _Session:
    """Holds the live path and document content for a research conversation."""

    path: Path | None = None
    document: str | None = None  # full file content including frontmatter
    continuing: Path | None = None
    queries: list = field(default_factory=list)  # all questions asked, in order
    created: str | None = None  # ISO timestamp of first save
    turns: int = 0  # number of completed research turns

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
            "queries": list(self.queries),
            "created": self.created,
            "updated": now,
            "turns": self.turns,
        }
        full = _persist.make_frontmatter(meta) + body
        _persist.save(self.path, full)
        self.document = full


@app.command()
def main(
    query: str | None = typer.Argument(
        None, help="Research question (omit to enter interactive REPL)"
    ),
    mode: str = typer.Option("balanced", "--mode", help="speed | balanced | quality"),
    llm_host: str | None = typer.Option(None, "--llm-host", envvar="SIFT_LLM_HOST"),
    llm_apikey: str | None = typer.Option(
        None, "--llm-apikey", envvar="SIFT_LLM_APIKEY"
    ),
    llm_model: str | None = typer.Option(None, "--llm-model", envvar="SIFT_LLM_MODEL"),
    embed_base_url: str | None = typer.Option(
        None, "--embed-base-url", envvar="SIFT_EMBED_BASE_URL"
    ),
    embed_api_key: str | None = typer.Option(
        None, "--embed-api-key", envvar="SIFT_EMBED_API_KEY"
    ),
    embed_model: str | None = typer.Option(
        None, "--embed-model", envvar="SIFT_EMBED_MODEL"
    ),
    system: str | None = typer.Option(
        None, "--system", help="System instructions injected into the writer prompt"
    ),
    history_file: Path | None = typer.Option(
        None, "--history-file", help="JSON file shaped as [[role, text], ...]"
    ),
    stream: bool = typer.Option(False, "--stream", help="Emit NDJSON events to stdout"),
    cont: Path | None = typer.Option(
        None, "--continue", "-c", help="Continue an existing research document"
    ),
    print_: bool = typer.Option(
        False,
        "--print",
        "-p",
        help="Non-interactive: print final answer to stdout and exit",
    ),
    lang: str = typer.Option("all", "--lang"),
    safesearch: int = typer.Option(0, "--safesearch", min=0, max=2),
    allow: list[str] = typer.Option(None, "--allow"),
    block: list[str] = typer.Option(None, "--block"),
    log_file: Path | None = typer.Option(None, "--log-file"),
    verbose: bool = typer.Option(False, "--verbose"),
    settings: Path | None = typer.Option(None, "--settings"),
    config: bool = typer.Option(
        False,
        "--config",
        help="Manage config (~/.config/sift/config.yaml) instead of researching. "
        "Use with --init, --edit, a bare KEY (get), or KEY=VALUE (set); alone it shows config.",
    ),
    config_init: bool = typer.Option(
        False, "--init", help="With --config: write a template and open $EDITOR."
    ),
    config_edit: bool = typer.Option(
        False, "--edit", help="With --config: open the config file in $EDITOR."
    ),
    force: bool = typer.Option(
        False, "--force", help="With --config --init: overwrite an existing file."
    ),
) -> None:
    """Research the web: plan → search → synthesize."""
    from . import config_file as _cf

    if config or config_init or config_edit:
        if not config:
            typer.echo("--init/--edit require --config", err=True)
            raise typer.Exit(code=2)
        try:
            code = _run_config(query, init=config_init, edit=config_edit, force=force)
        except _cf.ConfigFileError as exc:
            typer.echo(f"error: {exc}", err=True)
            code = 1
        raise typer.Exit(code=code)

    from . import bootstrap as _bootstrap

    _bootstrap.bootstrap(settings_path=settings, log_file=log_file, verbose=verbose)

    from . import llm_config
    from .research import embed_config as _embed_config

    try:
        llm_cfg = llm_config.resolve(host=llm_host, api_key=llm_apikey, model=llm_model)
        embed_cfg = _embed_config.resolve(
            host=embed_base_url, api_key=embed_api_key, model=embed_model
        )
    except _cf.ConfigFileError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)
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
        # Support both old "query" (scalar) and new "queries" (list) frontmatter.
        loaded_queries = meta.get("queries")
        if isinstance(loaded_queries, list):
            session.queries = loaded_queries
        elif meta.get("query"):
            session.queries = [meta["query"]]
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
        session.queries.append(query)

        import asyncio as _asyncio

        if stream:
            exit_code = _asyncio.run(
                _run_stream(
                    query=query,
                    history=history,
                    system=system,
                    mode=mode,
                    llm_cfg=llm_cfg,
                    embed_cfg=embed_cfg,
                    runner_kwargs=runner_kwargs,
                    session=session,
                )
            )
        else:
            doc = _asyncio.run(
                _run_quiet(
                    query=query,
                    history=history,
                    system=system,
                    mode=mode,
                    llm_cfg=llm_cfg,
                    embed_cfg=embed_cfg,
                    runner_kwargs=runner_kwargs,
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
        session.queries.append(query)
        exit_code = _asyncio.run(
            _run_stream(
                query=query,
                history=history,
                system=system,
                mode=mode,
                llm_cfg=llm_cfg,
                embed_cfg=embed_cfg,
                runner_kwargs=runner_kwargs,
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

    session.queries.append(query)

    import asyncio as _asyncio

    doc = _asyncio.run(
        _run_tui_turn(
            query=query,
            history=history,
            system=system,
            mode=mode,
            llm_cfg=llm_cfg,
            embed_cfg=embed_cfg,
            runner_kwargs=runner_kwargs,
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
        from .research import persist as _persist
        from .research import writer as _writer
        from .research.events import EventBus
        from . import config_file as _cf

        session.queries.append(q)
        bus = EventBus()
        base_dir = _cf.resolve_base_dir()
        guessed_scope = None
        guessed_file = None

        async def producer():
            nonlocal guessed_scope, guessed_file
            if session.path is None:
                guessed_scope, guessed_file = await _pick_or_exit(q, llm_cfg)
                session.path = _persist.resolve_path(
                    guessed_scope, guessed_file, base=base_dir, continuing=session.continuing
                )
            result = await _loop.run(
                query=q,
                history=session_history,
                system=system,
                mode=mode,
                llm_cfg=llm_cfg,
                embed_cfg=embed_cfg,
                bus=bus,
                runner_kwargs=runner_kwargs,
                document=session.body,
            )

            # Stage-2 correction: refine the location based on findings.
            if session.continuing is None and guessed_scope is not None and result.sources:
                sources_summary = "\n".join(
                    f"- {s.get('title', s.get('url', ''))}: {(s.get('content') or '')[:200]}"
                    for s in result.sources[:10]
                )
                corrected = await _persist.correct_location(
                    guessed_scope, guessed_file, sources_summary, llm_cfg
                )
                if corrected is not None:
                    corr_scope, corr_file = corrected
                    session.path = _persist.resolve_path(
                        corr_scope, corr_file, base=base_dir, continuing=session.continuing
                    )

            await _writer.write(
                query=q,
                history=session_history,
                system=system,
                sources=result.sources,
                mode=mode,
                llm_cfg=llm_cfg,
                bus=bus,
                existing_doc=session.body,
            )
            bus.close()

        prod = _asyncio.create_task(producer())
        updated_doc = await _tui.render_run(bus)
        await prod
        session_history.append(("human", q))
        session_history.append(("assistant", updated_doc))
        return updated_doc

    def _on_new() -> str | None:
        """Reset session state and prompt for a fresh research question."""
        # Reset session fields in-place (run_turn closure holds the ref).
        session.path = None
        session.document = None
        session.continuing = None
        session.queries = []
        session.created = None
        session.turns = 0

        # Reset conversation history to the original initial state.
        session_history.clear()
        session_history.extend(list(history))

        print()
        print("--- new session ---")
        try:
            q = input("research question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not q:
            return None
        return q

    _tui.followup_loop(run_turn, session, on_new=_on_new)
    raise typer.Exit(code=0)


async def _pick_or_exit(query, llm_cfg):
    """Resolve the initial (scope, file) guess, exiting cleanly on failure.

    There is no query-derived fallback: if the LLM cannot pick a location, we
    surface a readable error and exit rather than guessing from the query text.
    """
    from .research import persist as _persist

    try:
        return await _persist.pick_location(query, llm_cfg)
    except _persist.LocationError as exc:
        typer.echo(f"error: could not determine a save location: {exc}", err=True)
        raise typer.Exit(code=1)


async def _run_quiet(
    *,
    query,
    history,
    system,
    mode,
    llm_cfg,
    embed_cfg,
    runner_kwargs,
    session: _Session,
) -> str:
    """Run one research turn without the TUI. Returns the full document."""
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import persist as _persist
    from .research import writer as _writer
    from .research.events import EventBus, EventType
    from . import config_file as _cf

    bus = EventBus()
    base_dir = _cf.resolve_base_dir()

    # Drain the bus to stderr so non-TUI runs show progress instead of a silent
    # terminal that is indistinguishable from a hang. RESPONSE deltas are noisy
    # (the streamed answer) so they are summarised, not echoed verbatim.
    async def _progress():
        async for ev in bus.iterate():
            if ev.type == EventType.RESPONSE:
                continue
            sys.stderr.write(f"[sift] {ev.type.value}: {str(ev.data)[:160]}\n")
            sys.stderr.flush()

    progress_task = _asyncio.create_task(_progress())

    if session.path is None:
        scope, slug = await _pick_or_exit(query, llm_cfg)
        session.path = _persist.resolve_path(
            scope, slug, base=base_dir, continuing=session.continuing
        )

    result = await _loop.run(
        query=query,
        history=history,
        system=system,
        mode=mode,
        llm_cfg=llm_cfg,
        embed_cfg=embed_cfg,
        bus=bus,
        runner_kwargs=runner_kwargs,
        document=session.body,
    )

    # Stage-2 correction: refine the location based on what was actually found.
    if session.continuing is None and result.sources:
        sources_summary = "\n".join(
            f"- {s.get('title', s.get('url', ''))}: {(s.get('content') or '')[:200]}"
            for s in result.sources[:10]
        )
        corrected = await _persist.correct_location(
            scope, slug, sources_summary, llm_cfg
        )
        if corrected is not None:
            corr_scope, corr_file = corrected
            session.path = _persist.resolve_path(
                corr_scope, corr_file, base=base_dir, continuing=session.continuing
            )

    answer = await _writer.write(
        query=query,
        history=history,
        system=system,
        sources=result.sources,
        mode=mode,
        llm_cfg=llm_cfg,
        bus=bus,
        existing_doc=session.body,
    )
    bus.close()
    await progress_task

    body = (
        (_writer.close_dangling_fence(answer) + _writer.format_references(result.sources, answer))
        if answer
        else ""
    )
    if body:
        session.save(body)
    # Return only the body for stdout (session.save wraps with frontmatter).
    return body


async def _run_stream(
    *,
    query,
    history,
    system,
    mode,
    llm_cfg,
    embed_cfg,
    runner_kwargs,
    session: _Session,
) -> int:
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import persist as _persist
    from .research import writer as _writer
    from .research.events import Event, EventBus, EventType
    from . import config_file as _cf

    base_dir = _cf.resolve_base_dir()

    if session.path is None:
        scope, slug = await _pick_or_exit(query, llm_cfg)
        session.path = _persist.resolve_path(
            scope, slug, base=base_dir, continuing=session.continuing
        )

    bus = EventBus()
    saw_response = False
    accumulated = ""

    async def streamer():
        nonlocal saw_response, accumulated
        async for ev in bus.iterate():
            if ev.type == EventType.RESPONSE:
                saw_response = True
                accumulated += ev.data.get("delta", "")
            sys.stdout.write(
                json.dumps(
                    {"type": ev.type.value, "data": ev.data},
                    ensure_ascii=False,
                    default=str,
                )
            )
            sys.stdout.write("\n")
            sys.stdout.flush()

    stream_task = _asyncio.create_task(streamer())
    result = await _loop.run(
        query=query,
        history=history,
        system=system,
        mode=mode,
        llm_cfg=llm_cfg,
        embed_cfg=embed_cfg,
        bus=bus,
        runner_kwargs=runner_kwargs,
        document=session.body,
    )

    # Stage-2 correction: refine the location based on what was actually found.
    if session.continuing is None and result.sources:
        sources_summary = "\n".join(
            f"- {s.get('title', s.get('url', ''))}: {(s.get('content') or '')[:200]}"
            for s in result.sources[:10]
        )
        corrected = await _persist.correct_location(
            scope, slug, sources_summary, llm_cfg
        )
        if corrected is not None:
            corr_scope, corr_file = corrected
            session.path = _persist.resolve_path(
                corr_scope, corr_file, base=base_dir, continuing=session.continuing
            )

    await _writer.write(
        query=query,
        history=history,
        system=system,
        sources=result.sources,
        mode=mode,
        llm_cfg=llm_cfg,
        bus=bus,
        existing_doc=session.body,
    )
    bus.close()
    await stream_task

    if accumulated:
        full_doc = _writer.close_dangling_fence(accumulated) + _writer.format_references(result.sources, accumulated)
        session.save(full_doc)

    return 0 if saw_response else 1


async def _run_tui_turn(
    *,
    query,
    history,
    system,
    mode,
    llm_cfg,
    embed_cfg,
    runner_kwargs,
    session: _Session,
) -> str:
    """Run one research turn with the TUI. Picks location and saves. Returns full doc."""
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import persist as _persist
    from .research import tui as _tui
    from .research import writer as _writer
    from .research.events import EventBus
    from . import config_file as _cf

    bus = EventBus()
    base_dir = _cf.resolve_base_dir()
    guessed_scope = None
    guessed_file = None

    async def producer():
        nonlocal guessed_scope, guessed_file
        if session.path is None:
            guessed_scope, guessed_file = await _pick_or_exit(query, llm_cfg)
            session.path = _persist.resolve_path(
                guessed_scope, guessed_file, base=base_dir, continuing=session.continuing
            )

        result = await _loop.run(
            query=query,
            history=history,
            system=system,
            mode=mode,
            llm_cfg=llm_cfg,
            embed_cfg=embed_cfg,
            bus=bus,
            runner_kwargs=runner_kwargs,
            document=session.body,
        )

        # Stage-2 correction: refine the location based on findings.
        if session.continuing is None and guessed_scope is not None and result.sources:
            sources_summary = "\n".join(
                f"- {s.get('title', s.get('url', ''))}: {(s.get('content') or '')[:200]}"
                for s in result.sources[:10]
            )
            corrected = await _persist.correct_location(
                guessed_scope, guessed_file, sources_summary, llm_cfg
            )
            if corrected is not None:
                corr_scope, corr_file = corrected
                session.path = _persist.resolve_path(
                    corr_scope, corr_file, base=base_dir, continuing=session.continuing
                )

        await _writer.write(
            query=query,
            history=history,
            system=system,
            sources=result.sources,
            mode=mode,
            llm_cfg=llm_cfg,
            bus=bus,
            existing_doc=session.body,
        )
        bus.close()

    prod = _asyncio.create_task(producer())
    full_doc = await _tui.render_run(bus)
    await prod

    if full_doc:
        session.save(full_doc)
    return full_doc
