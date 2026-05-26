"""Rich Live TUI for `sift research --tui`.

Composes a compact action log (top) with a live-updating Markdown view
(bottom) that re-renders on every `response` delta. After the loop emits
`done`, exits Live and drops into an in-process REPL for follow-ups.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from .events import Event, EventBus, EventType
from .writer import format_references


async def render_run(
    bus: EventBus,
    *,
    on_done: Callable[[], None] | None = None,
) -> str:
    """Drain `bus` into a Rich Live view, return the accumulated markdown.

    The producer task (researcher + writer) must run concurrently with this
    coroutine and call `bus.close()` when finished.
    """
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()
    action_rows: list[tuple[str, str]] = []
    synthesis = ""
    start_time = time.monotonic()
    sources: list[dict[str, Any]] = []
    show_references = False

    # Per-query search status: query -> "running" | "done" | "failed"
    search_status: dict[str, str] = {}
    # Per-URL fetch status: url -> "fetching" | "done" | "failed"
    fetch_status: dict[str, str] = {}
    # Iteration progress
    current_iter = 0
    max_iter = 0

    def _elapsed() -> str:
        elapsed = time.monotonic() - start_time
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        return f"{mins}:{secs:02d}"

    def _iter_bar() -> Text:
        if max_iter == 0:
            return Text("")
        filled = "█" * current_iter
        empty = "·" * (max_iter - current_iter)
        bar = Text(f"{filled}{empty}", no_wrap=True)
        bar.stylize("green", 0, current_iter)
        bar.stylize("dim", current_iter, max_iter)
        return Text.assemble(bar, f" {current_iter}/{max_iter}")

    def _search_rows() -> list[tuple[str, str]]:
        rows = []
        for q, status in search_status.items():
            if status == "running":
                label = Text("search  ", style="yellow")
                query = Text(q, style="yellow dim")
            elif status == "done":
                label = Text("search  ", style="green")
                query = Text(q, style="green")
            else:
                label = Text("search  ", style="red")
                query = Text(q, style="red")
            rows.append((label, query))  # type: ignore[arg-type]
        return rows

    def _fetch_rows() -> list[tuple[str, str]]:
        rows = []
        for url, status in fetch_status.items():
            hostname = url.split("/")[2] if "://" in url else url
            if status == "fetching":
                label = Text("fetch   ", style="yellow")
                host = Text(hostname, style="yellow dim")
            elif status == "done":
                label = Text("fetch   ", style="green")
                host = Text(hostname, style="green")
            else:
                label = Text("fetch   ", style="red")
                host = Text(hostname, style="red")
            rows.append((label, host))  # type: ignore[arg-type]
        return rows

    def _render() -> Any:
        tbl = Table.grid(padding=(0, 1))
        tbl.add_column(style="cyan", no_wrap=True)
        tbl.add_column()

        # Iteration progress bar
        ib = _iter_bar()
        if ib.plain:
            tbl.add_row("iter    ", ib)

        # Elapsed time
        tbl.add_row("time    ", _elapsed())

        # Action log (last 12)
        for kind, detail in action_rows[-12:]:
            tbl.add_row(kind, detail)

        # Per-query search status
        for label, query in _search_rows():
            tbl.add_row(label, query)

        # Per-URL fetch status
        for label, host in _fetch_rows():
            tbl.add_row(label, host)

        title = f"actions ({_elapsed()})"
        if max_iter > 0:
            title += f" — iter {current_iter}/{max_iter}"
        top = Panel(tbl, title=title, title_align="left", border_style="dim")

        display_md = synthesis
        if show_references and sources:
            display_md += format_references(sources)
        md = Markdown(display_md or "_thinking…_")
        return Group(top, md)

    with Live(_render(), console=console, refresh_per_second=12, screen=False) as live:
        async for ev in bus.iterate():
            if ev.type == EventType.PLAN:
                action_rows.append(("plan", (ev.data.get("plan") or "")[:120]))
            elif ev.type == EventType.SEARCH:
                qs = ev.data.get("queries") or []
                action_rows.append(("search", ", ".join(qs)))
            elif ev.type == EventType.SEARCH_RESULTS:
                action_rows.append(("results", f"{ev.data.get('count', 0)} hits"))
            elif ev.type == EventType.SEARCH_QUERY:
                q = ev.data.get("query", "")
                status = ev.data.get("status", "")
                search_status[q] = status
            elif ev.type == EventType.READING:
                urls = ev.data.get("urls") or []
                action_rows.append(("reading", ", ".join(urls)[:120]))
            elif ev.type == EventType.FETCH_URL:
                url = ev.data.get("url", "")
                status = ev.data.get("status", "")
                fetch_status[url] = status
            elif ev.type == EventType.EXTRACTED:
                url = ev.data.get("url") or ""
                action_rows.append(("extracted", url))
            elif ev.type == EventType.RESPONSE:
                synthesis += ev.data.get("delta", "")
            elif ev.type == EventType.SOURCES:
                sources = ev.data.get("sources", [])
            elif ev.type == EventType.ITER_PROGRESS:
                current_iter = ev.data.get("iter", 0)
                max_iter = ev.data.get("max_iter", 0)
            elif ev.type == EventType.ERROR:
                action_rows.append(("error", str(ev.data)[:120]))
            elif ev.type == EventType.DONE:
                action_rows.append(("done", ""))
                show_references = True
            live.update(_render())
    if on_done:
        on_done()
    return synthesis + format_references(sources)


def followup_loop(
    run_one: Callable[[str, list[tuple[str, str]]], Awaitable[str]],
    initial_history: list[tuple[str, str]],
) -> None:
    """Synchronous follow-up REPL. Each turn appends (human, q) and
    (assistant, answer) to a shared history list.

    Special commands:
      w         — write the last answer to a markdown file
      blank     — exit
    """
    history = list(initial_history)
    last_synthesis = history[-1][1] if len(history) >= 2 else ""
    print()
    print("---  follow-up mode  (blank line or Ctrl-D to exit, 'w' to write to file)  ---")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not raw:
            return
        if raw == "w":
            _write_to_file(last_synthesis)
            continue
        try:
            answer = asyncio.run(run_one(raw, history))
        except KeyboardInterrupt:
            print()
            return
        history.append(("human", raw))
        history.append(("assistant", answer))
        last_synthesis = answer


def _write_to_file(synthesis: str) -> None:
    """Prompt for a file path and write synthesis to it."""
    try:
        path_str = input("file path: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not path_str:
        print("  cancelled")
        return
    path = Path(path_str).expanduser().resolve()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(synthesis)
        print(f"  written to {path}")
    except OSError as exc:
        print(f"  error: {exc}")
