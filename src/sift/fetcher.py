"""In-process crawl4ai wrapper.

Mirrors the filter selection of crawl4ai's `/md` HTTP endpoint
(`crawl4ai/deploy/docker/api.py:handle_markdown_request`) but runs in-process
via `AsyncWebCrawler`. Concurrency is bounded by an asyncio.Semaphore and each
URL is wrapped in `asyncio.wait_for` for timeout enforcement.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

log = logging.getLogger("sift.fetcher")

FilterName = Literal["fit", "raw", "bm25", "llm"]
ErrorType = Literal[
    "timeout", "http_error", "network", "filter_failed", "invalid_url"
]


@dataclass
class FetchOptions:
    filter: FilterName = "fit"
    query: str | None = None
    timeout: float = 20.0
    concurrency: int = 5
    log_file: Path | None = None
    # LLM filter knobs (only used when filter == "llm")
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_temperature: float | None = None
    # Post-extraction LLM pass (independent of `--filter llm`).
    prompt: str | None = None
    llm_config: "object | None" = None  # sift.llm_config.LLMConfig


@dataclass
class FetchedResult:
    url: str
    markdown: str | None
    filter: FilterName
    processed_markdown: str | None = None
    llm_error: str | None = None


@dataclass
class FetchError:
    url: str
    error_type: ErrorType
    message: str


@dataclass
class FetchOutcome:
    results: list[FetchedResult] = field(default_factory=list)
    errors: list[FetchError] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class CrawlImportError(RuntimeError):
    """Raised when the crawl4ai package cannot be imported."""


def _validate_url(url: str) -> str | None:
    """Return None if valid http(s) URL, else a short error message."""
    try:
        parts = urlsplit(url)
    except Exception as exc:  # urlsplit can raise on truly garbage strings
        return f"unparseable: {exc}"
    if parts.scheme not in ("http", "https"):
        return f"unsupported scheme: {parts.scheme or '(none)'}"
    if not parts.netloc:
        return "missing host"
    return None


def _build_markdown_generator(opts: FetchOptions):
    """Construct a DefaultMarkdownGenerator with the chosen content filter.

    Filter selection mirrors crawl4ai/deploy/docker/api.py:288-304.
    """
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    if opts.filter == "raw":
        return DefaultMarkdownGenerator()

    from crawl4ai.content_filter_strategy import (
        PruningContentFilter,
        BM25ContentFilter,
        LLMContentFilter,
    )

    if opts.filter == "fit":
        return DefaultMarkdownGenerator(content_filter=PruningContentFilter())
    if opts.filter == "bm25":
        if not opts.query:
            raise ValueError("--filter bm25 requires --query")
        return DefaultMarkdownGenerator(
            content_filter=BM25ContentFilter(user_query=opts.query)
        )
    if opts.filter == "llm":
        if not opts.query:
            raise ValueError("--filter llm requires --query")
        if not opts.llm_provider:
            raise ValueError(
                "--filter llm requires CRAWL4AI_LLM_PROVIDER (or --llm-provider)"
            )
        from crawl4ai import LLMConfig

        return DefaultMarkdownGenerator(
            content_filter=LLMContentFilter(
                llm_config=LLMConfig(
                    provider=opts.llm_provider,
                    api_token=opts.llm_api_key,
                    temperature=opts.llm_temperature,
                    base_url=opts.llm_base_url,
                ),
                instruction=opts.query,
            )
        )
    raise ValueError(f"unknown filter: {opts.filter}")


def _classify_exception(exc: BaseException) -> tuple[ErrorType, str]:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout", "timed out"
    name = type(exc).__name__.lower()
    msg = str(exc) or type(exc).__name__
    if "timeout" in name:
        return "timeout", msg
    if "http" in name or "status" in name:
        return "http_error", msg
    if "dns" in name or "connection" in name or "network" in name:
        return "network", msg
    return "network", msg


async def _fetch_one(
    crawler,
    crawler_run_config,
    url: str,
    filter_name: FilterName,
    timeout: float,
    sem: asyncio.Semaphore,
    prompt: str | None = None,
    llm_config=None,
) -> FetchedResult | FetchError:
    async with sem:
        try:
            result = await asyncio.wait_for(
                crawler.arun(url=url, config=crawler_run_config),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return FetchError(url=url, error_type="timeout", message="timed out")
        except Exception as exc:
            etype, msg = _classify_exception(exc)
            log.exception("fetch failed for %s", url)
            return FetchError(url=url, error_type=etype, message=msg)

    if not getattr(result, "success", False):
        msg = getattr(result, "error_message", "") or "crawl unsuccessful"
        return FetchError(url=url, error_type="http_error", message=msg)

    try:
        md_obj = result.markdown
        if filter_name == "raw":
            text = md_obj.raw_markdown
        else:
            text = md_obj.fit_markdown
    except Exception as exc:
        return FetchError(
            url=url, error_type="filter_failed", message=str(exc) or "no markdown"
        )

    result = FetchedResult(url=url, markdown=text or None, filter=filter_name)

    if prompt and llm_config is not None and result.markdown:
        from . import llm as _llm

        processed, err = await _llm.process_page_content(
            result.markdown, llm_config, prompt
        )
        result.processed_markdown = processed
        result.llm_error = err
    return result


async def _run(urls: list[str], opts: FetchOptions) -> FetchOutcome:
    try:
        from crawl4ai import (
            AsyncWebCrawler,
            BrowserConfig,
            CrawlerRunConfig,
            CacheMode,
        )
    except ImportError as exc:
        raise CrawlImportError(f"crawl4ai is not installed: {exc}") from exc

    from crawl4ai.async_logger import AsyncLogger

    # Validate URLs up front; queue valid ones, collect invalid as errors.
    queued: list[str] = []
    errors: list[FetchError] = []
    for url in urls:
        err = _validate_url(url)
        if err is None:
            queued.append(url)
        else:
            errors.append(
                FetchError(url=url, error_type="invalid_url", message=err)
            )

    if not queued:
        return FetchOutcome(results=[], errors=errors, elapsed_seconds=0.0)

    # ValueError (bad filter/query/llm config) propagates to the CLI.
    md_gen = _build_markdown_generator(opts)

    crawler_run_config = CrawlerRunConfig(
        markdown_generator=md_gen,
        cache_mode=CacheMode.WRITE_ONLY,
        verbose=False,
    )

    crawl_logger = AsyncLogger(
        log_file=str(opts.log_file) if opts.log_file else None,
        verbose=False,
    )
    browser_cfg = BrowserConfig(headless=True, verbose=False)

    sem = asyncio.Semaphore(max(1, opts.concurrency))
    loop = asyncio.get_event_loop()
    start = loop.time()

    async with AsyncWebCrawler(config=browser_cfg, logger=crawl_logger) as crawler:
        tasks = [
            _fetch_one(
                crawler, crawler_run_config, u, opts.filter, opts.timeout, sem,
                prompt=opts.prompt, llm_config=opts.llm_config,
            )
            for u in queued
        ]
        finished = await asyncio.gather(*tasks)

    elapsed = loop.time() - start

    results: list[FetchedResult] = []
    for item in finished:
        if isinstance(item, FetchedResult):
            results.append(item)
        else:
            errors.append(item)

    return FetchOutcome(results=results, errors=errors, elapsed_seconds=elapsed)


def fetch_urls(urls: list[str], opts: FetchOptions) -> FetchOutcome:
    """Fetch markdown for each URL with bounded concurrency.

    Synchronous wrapper around the async pipeline so the CLI can call it
    without leaking asyncio details.
    """
    return asyncio.run(_run(urls, opts))
