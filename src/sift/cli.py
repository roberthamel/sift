"""Typer entry point for `sift`."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=False, add_completion=False)
log = logging.getLogger("sift")


@app.command()
def main(
    query: str | None = typer.Argument(None, help="Research question (omit to enter interactive TUI)"),
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
    output: Path | None = typer.Option(None, "--output", "-o", help="Write synthesis to this markdown file"),
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

    if output is not None and query is None:
        typer.echo("a question is required when -o is given", err=True)
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

    if query is None:
        try:
            query = input("research question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise typer.Exit(code=1)
        if not query:
            typer.echo("no query provided", err=True)
            raise typer.Exit(code=2)
        _run_tui(
            query=query, history=history, system=system, mode=mode,
            llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
            output=output, repl=True,
        )
        return

    if stream:
        import asyncio
        exit_code = asyncio.run(
            _run_stream(
                query=query, history=history, system=system, mode=mode,
                llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
                output=output,
            )
        )
        raise typer.Exit(code=exit_code)

    answer = _run_tui(
        query=query, history=history, system=system, mode=mode,
        llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
        output=output, repl=False,
    )
    raise typer.Exit(code=0 if answer else 1)


async def _run_stream(*, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs, output=None):
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import writer as _writer
    from .research.events import EventBus, EventType

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
    )
    await _writer.write(
        query=query, history=history, system=system,
        sources=result.sources, mode=mode, llm_cfg=llm_cfg, bus=bus,
    )
    bus.close()
    await stream_task

    if output and accumulated:
        from .research import writer as _writer2
        synthesis_with_refs = accumulated + _writer2.format_references(result.sources, accumulated)
        output.write_text(synthesis_with_refs)

    return 0 if saw_response else 1


def _run_tui(*, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs, output=None, repl=True):
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import writer as _writer
    from .research import tui as _tui
    from .research.events import EventBus

    async def one_turn(q: str, hist: list[tuple[str, str]]) -> str:
        bus = EventBus()

        async def producer():
            result = await _loop.run(
                query=q, history=hist, system=system, mode=mode,
                llm_cfg=llm_cfg, embed_cfg=embed_cfg, bus=bus, runner_kwargs=runner_kwargs,
            )
            await _writer.write(
                query=q, history=hist, system=system,
                sources=result.sources, mode=mode, llm_cfg=llm_cfg, bus=bus,
            )
            bus.close()

        prod = _asyncio.create_task(producer())
        synthesis = await _tui.render_run(bus)
        await prod
        return synthesis

    answer = _asyncio.run(one_turn(query, history))

    if output:
        output.write_text(answer)

    if not repl:
        return answer

    session_history = list(history)
    session_history.append(("human", query))
    session_history.append(("assistant", answer))

    def _run_one(q: str, hist: list[tuple[str, str]]):
        return one_turn(q, hist)

    _tui.followup_loop(_run_one, session_history)
    return answer
