"""Typer entry point for `sift`."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger("sift")

HARD_CAP = 50


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
    fetch_top: int = typer.Option(5, "--fetch-top", min=0, help="How many results to fetch (0 = all, capped at 50)"),
    fetch_concurrency: int = typer.Option(5, "--concurrency", min=1, help="Parallel fetches"),
    fetch_timeout: float = typer.Option(20.0, "--timeout-fetch", min=0.1, help="Per-URL fetch timeout"),
    fetch_filter: str = typer.Option("fit", "--filter", help="Content filter: fit, raw, bm25, llm"),
    fetch_query: str | None = typer.Option(None, "--query", help="Filter query (defaults to search query for bm25/llm)"),
) -> None:
    """Run a SearXNG search in-process and print JSON to stdout."""
    from . import bootstrap as _bootstrap

    resolved_log = _bootstrap.bootstrap(settings_path=settings, log_file=log_file, verbose=verbose)

    from . import runner, pretty as pretty_mod

    engine_names = (
        [e.strip() for e in engines.split(",") if e.strip()] if engines else None
    )

    try:
        result = runner.run_search(
            query=query,
            engine_names=engine_names,
            category=category,
            page=page,
            lang=lang,
            safesearch=safesearch,
            timeout=timeout,
        )
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

    if fetch:
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

    opts = fetcher.FetchOptions(
        filter=filter_,  # type: ignore[arg-type]
        query=query,
        timeout=timeout,
        concurrency=concurrency,
        log_file=resolved_log,
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
