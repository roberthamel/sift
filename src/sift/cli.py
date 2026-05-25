"""Typer entry point for `sift`."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger("sift")

HARD_CAP = 100


@app.callback()
def _root() -> None:
    """sift — search the web via SearXNG and read pages via crawl4ai, in-process."""


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    engines: str | None = typer.Option(None, "--engines", help="Comma-separated engine names"),
    category: str = typer.Option("general", "--category"),
    page: int = typer.Option(1, "--page", min=1),
    lang: str = typer.Option("all", "--lang"),
    safesearch: int = typer.Option(0, "--safesearch", min=0, max=2),
    timeout: float | None = typer.Option(None, "--timeout"),
    settings: Path | None = typer.Option(None, "--settings", help="Override settings.yml path"),
    log_file: Path | None = typer.Option(None, "--log-file"),
    verbose: bool = typer.Option(False, "--verbose"),
    pretty: bool = typer.Option(False, "--pretty", help="Human-readable instead of JSON"),
    fetch: bool = typer.Option(False, "--fetch", help="Also fetch markdown for the top results"),
    fetch_top: int = typer.Option(10, "--fetch-top", min=0, help="How many results to fetch (0 = all, capped at 100)"),
    fetch_concurrency: int = typer.Option(5, "--concurrency", min=1, help="Parallel fetches"),
    fetch_timeout: float = typer.Option(20.0, "--timeout-fetch", min=0.1, help="Per-URL fetch timeout"),
    fetch_filter: str = typer.Option("fit", "--filter", help="Content filter: fit, raw, bm25, llm"),
    fetch_query: str | None = typer.Option(None, "--query", help="Filter query (defaults to search query for bm25/llm)"),
    allow: list[str] = typer.Option(None, "--allow", help="Keep only URLs whose host ends in this domain (repeatable)"),
    block: list[str] = typer.Option(None, "--block", help="Drop URLs whose host ends in this domain (repeatable)"),
    summary: bool = typer.Option(False, "--summary", help="After fetching, run LLM synthesis and attach `summary`"),
    llm_host: str | None = typer.Option(None, "--llm-host", envvar="SIFT_LLM_HOST"),
    llm_apikey: str | None = typer.Option(None, "--llm-apikey", envvar="SIFT_LLM_APIKEY"),
    llm_model: str | None = typer.Option(None, "--llm-model", envvar="SIFT_LLM_MODEL"),
    cache_ttl: float = typer.Option(3600.0, "--cache-ttl", min=0, help="Seconds to keep cached entries (0 = never expire)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass cache for both read and write"),
) -> None:
    """Run a SearXNG search in-process and print JSON to stdout."""
    from . import bootstrap as _bootstrap

    resolved_log = _bootstrap.bootstrap(settings_path=settings, log_file=log_file, verbose=verbose)

    from . import runner, pretty as pretty_mod

    engine_names = (
        [e.strip() for e in engines.split(",") if e.strip()] if engines else None
    )

    from . import cache as _cache

    cache_key = _cache.make_key("search", {
        "query": query,
        "engines": engine_names,
        "category": category,
        "page": page,
        "lang": lang,
        "safesearch": safesearch,
        "allow": sorted(allow or []),
        "block": sorted(block or []),
    })
    cached = None if no_cache else _cache.get("search", cache_key, cache_ttl)

    try:
        if cached is not None:
            result = cached
        else:
            result = runner.run_search(
                query=query,
                engine_names=engine_names,
                category=category,
                page=page,
                lang=lang,
                safesearch=safesearch,
                timeout=timeout,
            )
            if not no_cache:
                _cache.set("search", cache_key, result)
    except runner._engines.UnknownEngineError as exc:
        msg = f"unknown engine: {exc}"
        log.error(msg)
        typer.echo(msg, err=True)
        raise typer.Exit(code=1)
    except runner.InitError as exc:
        msg = f"initialization failed: {exc}"
        log.error(msg)
        typer.echo(msg, err=True)
        raise typer.Exit(code=2)

    if allow or block:
        result["results"] = runner.apply_domain_filters(
            result.get("results", []) or [], allow, block
        )
        result["number_of_results"] = len(result["results"])

    if fetch or summary:
        urls = [r["url"] for r in result.get("results", []) if r.get("url")]
        if fetch_top > 0:
            urls = urls[:fetch_top]
        urls = urls[:HARD_CAP]
        result = _run_fetch_into_search(
            search_dict=result,
            urls=urls,
            filter_name=fetch_filter,
            query=fetch_query or query,
            concurrency=fetch_concurrency,
            timeout=fetch_timeout,
            log_file=resolved_log,
        )

    if summary:
        from . import llm_config, synthesize as synth_mod

        cfg = llm_config.resolve(host=llm_host, api_key=llm_apikey, model=llm_model)
        try:
            cfg.for_llm()
        except llm_config.ConfigError as exc:
            log.warning("synthesis skipped: %s", exc)
            result["summary"] = None
            result["llm_error"] = str(exc)
        else:
            payload = synth_mod.build_synthesize_payload(result, query)
            synth_out, _err = synth_mod.synthesize(payload, cfg)
            result["summary"] = synth_out.get("summary")
            if synth_out.get("llm_error"):
                result["llm_error"] = synth_out["llm_error"]

    if pretty:
        sys.stdout.write(pretty_mod.render(result))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        sys.stdout.write("\n")


@app.command()
def fetch(
    urls: list[str] = typer.Argument(None, help="URLs to fetch (omit to read from stdin)"),
    concurrency: int = typer.Option(5, "--concurrency", min=1, help="Parallel fetches"),
    timeout: float = typer.Option(20.0, "--timeout", min=0.1, help="Per-URL timeout in seconds"),
    filter_: str = typer.Option("fit", "--filter", help="Content filter: fit, raw, bm25, llm"),
    query: str | None = typer.Option(None, "--query", help="Filter query (required for bm25/llm)"),
    prompt: str | None = typer.Option(None, "--prompt", help="Post-extraction LLM pass; attaches processed_markdown to each result"),
    llm_host: str | None = typer.Option(None, "--llm-host", envvar="SIFT_LLM_HOST"),
    llm_apikey: str | None = typer.Option(None, "--llm-apikey", envvar="SIFT_LLM_APIKEY"),
    llm_model: str | None = typer.Option(None, "--llm-model", envvar="SIFT_LLM_MODEL"),
    log_file: Path | None = typer.Option(None, "--log-file"),
    verbose: bool = typer.Option(False, "--verbose"),
    pretty: bool = typer.Option(False, "--pretty", help="Human-readable instead of JSON"),
    settings: Path | None = typer.Option(None, "--settings", help="Override settings.yml path (kept for parity)"),
) -> None:
    """Fetch markdown for URLs via crawl4ai (in-process).

    URLs come from positional args, or stdin if no args are given. Stdin may
    be a raw URL list (one per line, `#` comments allowed) or the JSON output
    of `sift search`, in which case result URLs are extracted.
    """
    from . import bootstrap as _bootstrap
    from . import inputs

    resolved_log = _bootstrap.bootstrap(settings_path=settings, log_file=log_file, verbose=verbose)

    positional = [u for u in (urls or []) if u]
    resolved = inputs.resolve(
        args=positional, stdin=sys.stdin, stdin_is_tty=sys.stdin.isatty()
    )

    if not resolved.urls:
        typer.echo("no URLs supplied (pass as args or pipe via stdin)", err=True)
        raise typer.Exit(code=2)

    if len(resolved.urls) > HARD_CAP:
        typer.echo(
            f"too many URLs: {len(resolved.urls)} (hard cap is {HARD_CAP})",
            err=True,
        )
        raise typer.Exit(code=2)

    from . import fetcher, serialize, pretty as pretty_mod

    llm_cfg = None
    if prompt:
        from . import llm_config as _llm_config

        llm_cfg = _llm_config.resolve(host=llm_host, api_key=llm_apikey, model=llm_model)
        try:
            llm_cfg.for_llm()
        except _llm_config.ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2)

    opts = fetcher.FetchOptions(
        filter=filter_,  # type: ignore[arg-type]
        query=query,
        timeout=timeout,
        concurrency=concurrency,
        log_file=resolved_log,
        prompt=prompt,
        llm_config=llm_cfg,
    )

    try:
        outcome = fetcher.fetch_urls(resolved.urls, opts)
    except fetcher.CrawlImportError as exc:
        typer.echo(f"crawl4ai unavailable: {exc}", err=True)
        raise typer.Exit(code=3)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    doc = serialize.fetched_to_dict(outcome, search_json=resolved.search_json)

    if not outcome.results and outcome.errors:
        # All URLs failed.
        if pretty:
            sys.stdout.write(pretty_mod.render_fetch(doc))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(json.dumps(doc, ensure_ascii=False, default=str))
            sys.stdout.write("\n")
        raise typer.Exit(code=1)

    if pretty:
        sys.stdout.write(pretty_mod.render_fetch(doc))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(doc, ensure_ascii=False, default=str))
        sys.stdout.write("\n")


@app.command()
def synthesize(
    query: str = typer.Argument(..., help="The query the LLM should answer using the piped sources"),
    llm_host: str | None = typer.Option(None, "--llm-host", envvar="SIFT_LLM_HOST"),
    llm_apikey: str | None = typer.Option(None, "--llm-apikey", envvar="SIFT_LLM_APIKEY"),
    llm_model: str | None = typer.Option(None, "--llm-model", envvar="SIFT_LLM_MODEL"),
    pretty: bool = typer.Option(False, "--pretty", help="Human-readable instead of JSON"),
) -> None:
    """LLM-synthesize a summary from piped search/fetch JSON on stdin."""
    from . import llm_config, synthesize as synth_mod, pretty as pretty_mod

    cfg = llm_config.resolve(host=llm_host, api_key=llm_apikey, model=llm_model)
    try:
        cfg.for_llm()
    except llm_config.ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    if sys.stdin.isatty():
        typer.echo("no input on stdin (pipe sift search / sift fetch output in)", err=True)
        raise typer.Exit(code=2)

    raw = sys.stdin.read()
    stdin_doc: object
    try:
        stdin_doc = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        typer.echo(f"stdin is not valid JSON: {exc}", err=True)
        raise typer.Exit(code=2)

    payload = synth_mod.build_synthesize_payload(stdin_doc, query)
    out, _err = synth_mod.synthesize(payload, cfg)

    if pretty:
        sys.stdout.write(pretty_mod.render_synthesize(out))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
        sys.stdout.write("\n")


cache_app = typer.Typer(no_args_is_help=True, help="Inspect or clear sift's on-disk cache.")
app.add_typer(cache_app, name="cache")


@cache_app.command("stats")
def cache_stats() -> None:
    """Print entry count and total byte size of the cache."""
    from . import cache as _cache

    s = _cache.stats()
    out = {"root": s.root, "entries": s.entries, "bytes": s.bytes}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete every cache entry. Prints the number removed."""
    from . import cache as _cache

    n = _cache.clear()
    sys.stdout.write(json.dumps({"removed": n}) + "\n")


@app.command()
def describe(
    image: str = typer.Argument(..., help="Path, http(s) URL, data: URL, or raw base64 of an image"),
    prompt: str | None = typer.Option(None, "--prompt", help="Custom prompt for the VLM"),
    max_bytes: int = typer.Option(10 * 1024 * 1024, "--max-bytes", min=1, help="Reject images larger than this"),
    vlm: bool = typer.Option(False, "--vlm", help="Assert the configured model has vision capabilities"),
    llm_host: str | None = typer.Option(None, "--llm-host", envvar="SIFT_LLM_HOST"),
    llm_apikey: str | None = typer.Option(None, "--llm-apikey", envvar="SIFT_LLM_APIKEY"),
    llm_model: str | None = typer.Option(None, "--llm-model", envvar="SIFT_LLM_MODEL"),
    pretty: bool = typer.Option(False, "--pretty", help="Human-readable instead of JSON"),
) -> None:
    """Describe an image via a vision-capable LLM."""
    import asyncio

    from . import llm as _llm
    from . import llm_config, images, pretty as pretty_mod

    cfg = llm_config.resolve(host=llm_host, api_key=llm_apikey, model=llm_model, vlm=vlm or None)
    try:
        cfg.for_vlm()
    except llm_config.ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)

    try:
        data, mime = images.resolve_image(image, max_bytes=max_bytes)
    except images.ImageError as exc:
        out = {
            "source": image,
            "success": False,
            "error": str(exc),
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        raise typer.Exit(code=1)

    desc, err = asyncio.run(_llm.process_image_content(data, mime, cfg, prompt))
    out = {
        "source": image,
        "mime": mime,
        "bytes": len(data),
        "success": err is None,
        "model": cfg.model,
    }
    if err is None:
        out["description"] = desc
    else:
        out["description"] = None
        out["error"] = err

    if pretty:
        sys.stdout.write(pretty_mod.render_describe(out))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
        sys.stdout.write("\n")


@app.command()
def research(
    query: str = typer.Argument(..., help="Research question"),
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
    tui: bool = typer.Option(False, "--tui", help="Rich Live TUI + follow-up REPL"),
    lang: str = typer.Option("all", "--lang"),
    safesearch: int = typer.Option(0, "--safesearch", min=0, max=2),
    allow: list[str] = typer.Option(None, "--allow"),
    block: list[str] = typer.Option(None, "--block"),
    log_file: Path | None = typer.Option(None, "--log-file"),
    verbose: bool = typer.Option(False, "--verbose"),
    settings: Path | None = typer.Option(None, "--settings"),
) -> None:
    """Vane-style research loop: plan → search → synthesize."""
    import asyncio

    from . import bootstrap as _bootstrap

    _bootstrap.bootstrap(settings_path=settings, log_file=log_file, verbose=verbose)

    from . import llm_config
    from .research import embed_config as _embed_config
    from .research import loop as _loop
    from .research import writer as _writer
    from .research.events import Event, EventBus, EventType

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

    if tui:
        _run_tui(
            query=query, history=history, system=system, mode=mode,
            llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
        )
        return

    if stream:
        exit_code = asyncio.run(
            _run_stream(
                query=query, history=history, system=system, mode=mode,
                llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
            )
        )
        raise typer.Exit(code=exit_code)

    exit_code = asyncio.run(
        _run_json(
            query=query, history=history, system=system, mode=mode,
            llm_cfg=llm_cfg, embed_cfg=embed_cfg, runner_kwargs=runner_kwargs,
        )
    )
    raise typer.Exit(code=exit_code)


async def _run_json(*, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs):
    import asyncio
    from .research import loop as _loop
    from .research import writer as _writer
    from .research.events import EventBus, EventType

    bus = EventBus()
    errors: list[dict] = []
    actions_log: list[dict] = []

    async def collector():
        async for ev in bus.iterate():
            if ev.type == EventType.ERROR:
                errors.append(ev.data)
            elif ev.type in (
                EventType.PLAN, EventType.SEARCH, EventType.SEARCH_RESULTS,
                EventType.READING, EventType.EXTRACTED, EventType.DONE,
            ):
                actions_log.append({"type": ev.type.value, "data": ev.data})

    collect_task = asyncio.create_task(collector())

    result = await _loop.run(
        query=query, history=history, system=system, mode=mode,
        llm_cfg=llm_cfg, embed_cfg=embed_cfg, bus=bus, runner_kwargs=runner_kwargs,
    )
    synthesis = await _writer.write(
        query=query, history=history, system=system,
        sources=result.sources, mode=mode, llm_cfg=llm_cfg, bus=bus,
    )
    bus.close()
    await collect_task

    out = {
        "query": query,
        "mode": mode,
        "actions": actions_log,
        "sources": result.sources,
        "synthesis": synthesis,
        "usage": result.usage,
        "errors": errors,
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
    sys.stdout.write("\n")
    return 0 if synthesis else 1


async def _run_stream(*, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs):
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import writer as _writer
    from .research.events import EventBus, EventType

    bus = EventBus()
    saw_response = False

    async def streamer():
        nonlocal saw_response
        async for ev in bus.iterate():
            if ev.type == EventType.RESPONSE:
                saw_response = True
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
    return 0 if saw_response else 1


def _run_tui(*, query, history, system, mode, llm_cfg, embed_cfg, runner_kwargs):
    import asyncio as _asyncio
    from .research import loop as _loop
    from .research import writer as _writer
    from .research import tui as _tui
    from .research.events import EventBus

    session_history = list(history)

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

    answer = _asyncio.run(one_turn(query, session_history))

    def _run_one(q: str, hist: list[tuple[str, str]]):
        return one_turn(q, hist)

    session_history.append(("human", query))
    session_history.append(("assistant", answer))
    _tui.followup_loop(_run_one, session_history)


def _run_fetch_into_search(
    *,
    search_dict: dict,
    urls: list[str],
    filter_name: str,
    query: str | None,
    concurrency: int,
    timeout: float,
    log_file: Path | None,
) -> dict:
    """Helper used by `search --fetch`. Fetch failures never demote exit code."""
    from . import fetcher, serialize

    opts = fetcher.FetchOptions(
        filter=filter_name,  # type: ignore[arg-type]
        query=query,
        timeout=timeout,
        concurrency=concurrency,
        log_file=log_file,
    )
    try:
        outcome = fetcher.fetch_urls(urls, opts)
    except (fetcher.CrawlImportError, ValueError) as exc:
        log.warning("fetch skipped: %s", exc)
        outcome = fetcher.FetchOutcome(
            results=[],
            errors=[
                fetcher.FetchError(url=u, error_type="network", message=str(exc))
                for u in urls
            ],
        )
    return serialize.embed_fetch_into_search(search_dict, outcome)
