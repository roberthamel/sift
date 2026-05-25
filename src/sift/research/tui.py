"""Rich Live TUI for `sift research --tui`.

Composes a compact action log (top) with a live-updating Markdown view
(bottom) that re-renders on every `response` delta. After the loop emits
`done`, exits Live and drops into an in-process REPL for follow-ups.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Awaitable, Callable

from .events import Event, EventBus, EventType


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

    console = Console()
    action_rows: list[tuple[str, str]] = []
    synthesis = ""

    def _render() -> Any:
        tbl = Table.grid(padding=(0, 1))
        tbl.add_column(style="cyan", no_wrap=True)
        tbl.add_column()
        for kind, detail in action_rows[-12:]:
            tbl.add_row(kind, detail)
        top = Panel(tbl, title="actions", title_align="left", border_style="dim")
        md = Markdown(synthesis or "_thinking…_")
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
            elif ev.type == EventType.READING:
                urls = ev.data.get("urls") or []
                action_rows.append(("reading", ", ".join(urls)[:120]))
            elif ev.type == EventType.EXTRACTED:
                url = ev.data.get("url") or ""
                action_rows.append(("extracted", url))
            elif ev.type == EventType.RESPONSE:
                synthesis += ev.data.get("delta", "")
            elif ev.type == EventType.ERROR:
                action_rows.append(("error", str(ev.data)[:120]))
            elif ev.type == EventType.DONE:
                action_rows.append(("done", ""))
            live.update(_render())
    if on_done:
        on_done()
    return synthesis


def followup_loop(
    run_one: Callable[[str, list[tuple[str, str]]], Awaitable[str]],
    initial_history: list[tuple[str, str]],
) -> None:
    """Synchronous follow-up REPL. Each turn appends (human, q) and
    (assistant, answer) to a shared history list."""
    history = list(initial_history)
    print()
    print("---  follow-up mode  (blank line or Ctrl-D to exit)  ---")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not q:
            return
        try:
            answer = asyncio.run(run_one(q, history))
        except KeyboardInterrupt:
            print()
            return
        history.append(("human", q))
        history.append(("assistant", answer))
