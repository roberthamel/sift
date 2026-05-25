"""Human-readable text renderer for a serialized result dict."""
from __future__ import annotations

from io import StringIO


def render(d: dict) -> str:
    out = StringIO()
    query = d.get("query", "")
    out.write(f'Results for "{query}" ({d.get("number_of_results", 0)} hits, '
              f'{d.get("elapsed_seconds", 0)}s)\n')

    for i, r in enumerate(d.get("results", []), 1):
        out.write(f"\n{i}. {r.get('title', '')}\n")
        out.write(f"   {r.get('url', '')}\n")
        if r.get("content"):
            out.write(f"   {r['content']}\n")
        out.write(f"   [{r.get('engine', '')}]\n")
        if r.get("markdown"):
            out.write("\n")
            out.write(r["markdown"])
            out.write("\n")

    if answers := d.get("answers"):
        out.write("\nAnswers:\n")
        for a in answers:
            out.write(f"  - {a.get('answer') or a}\n")

    if infos := d.get("infoboxes"):
        out.write(f"\nInfoboxes: {len(infos)}\n")

    if sugs := d.get("suggestions"):
        out.write("\nSuggestions: " + ", ".join(sugs) + "\n")

    if unresp := d.get("unresponsive_engines"):
        out.write("\nUnresponsive engines:\n")
        for u in unresp:
            out.write(f"  - {u['engine']}: {u['error_type']}\n")

    if errs := d.get("fetch_errors"):
        out.write("\nFetch errors:\n")
        for e in errs:
            out.write(f"  - {e['url']}: {e['error_type']} ({e['message']})\n")

    if summary := d.get("summary"):
        out.write("\nSummary:\n")
        out.write(summary)
        out.write("\n")
    if d.get("llm_error"):
        out.write(f"\nLLM error: {d['llm_error']}\n")

    return out.getvalue()


def render_synthesize(d: dict) -> str:
    out = StringIO()
    out.write(f'Summary for "{d.get("query", "")}" '
              f'({d.get("source_count", 0)} sources, model={d.get("model", "")})\n')
    if d.get("snippet_only"):
        out.write("(synthesizing from snippets only — no fetched content)\n")
    summary = d.get("summary")
    if summary:
        out.write("\n")
        out.write(summary)
        out.write("\n")
    if d.get("llm_error"):
        out.write(f"\nLLM error: {d['llm_error']}\n")
    return out.getvalue()


def render_describe(d: dict) -> str:
    out = StringIO()
    src = d.get("source", "")
    out.write(f"Describe {src} ({d.get('mime', '')}, {d.get('bytes', 0)} bytes)\n")
    if d.get("success"):
        out.write("\n")
        out.write(d.get("description") or "")
        out.write("\n")
    else:
        out.write(f"\nError: {d.get('error', 'unknown')}\n")
    return out.getvalue()


def render_fetch(d: dict) -> str:
    out = StringIO()
    results = d.get("results", []) or []
    errors = d.get("fetch_errors", []) or []
    out.write(
        f"Fetched {len(results)} URL(s), {len(errors)} error(s), "
        f"{d.get('elapsed_seconds', 0)}s\n"
    )
    for i, r in enumerate(results, 1):
        out.write(f"\n--- {i}. {r.get('url', '')} [{r.get('filter', '')}] ---\n")
        if r.get("title"):
            out.write(f"{r['title']}\n")
        md = r.get("markdown")
        if md:
            out.write("\n")
            out.write(md)
            out.write("\n")
        else:
            out.write("(no markdown)\n")
        if r.get("processed_markdown"):
            out.write("\nProcessed:\n")
            out.write(r["processed_markdown"])
            out.write("\n")
        if r.get("llm_error"):
            out.write(f"\nLLM error: {r['llm_error']}\n")
    if errors:
        out.write("\nErrors:\n")
        for e in errors:
            out.write(f"  - {e['url']}: {e['error_type']} ({e['message']})\n")
    return out.getvalue()
