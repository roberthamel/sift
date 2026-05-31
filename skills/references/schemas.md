# sift output schemas

## Default one-shot output

When run as `sift "q"` (no `--stream`, no `-o`), sift renders a Rich Live
TUI to the terminal showing the actions panel + streaming markdown answer.
There is no JSON written to stdout in this mode.

## `-o` / `--output` file

When `-o file.md` is given, sift writes a markdown file containing the
synthesized answer plus inline citations:

```markdown
The answer to your question... [1] ... more content ... [2].

## References

1. [Title A](https://example.com/a) — snippet or description
2. [Title B](https://example.com/b) — snippet or description
```

## `--stream` NDJSON events

With `--stream`, one JSON object per line is written to stdout. Each line
is a complete JSON object with `type` and `data` fields.

### Event types

| Type | `data` fields | Notes |
|------|--------------|-------|
| `init` | `{"query": "...", "mode": "..."}` | First event |
| `plan` | `{"plan": "..."}` | LLM-generated research plan |
| `search` | `{"queries": ["q1", "q2"]}` | Search queries issued |
| `search_query` | `{"query": "...", "status": "running"\|"done"\|"failed"}` | Per-query status |
| `search_results` | `{"count": N}` | Results returned |
| `reading` | `{"urls": ["..."]}` | URLs being scraped |
| `fetch_url` | `{"url": "...", "status": "fetching"\|"done"\|"failed"}` | Per-URL status |
| `extracted` | `{"url": "..."}` | URL successfully extracted |
| `iter_progress` | `{"iter": N, "max_iter": N}` | Loop iteration progress |
| `response` | `{"delta": "..."}` | Streaming answer chunk (concatenate for full synthesis) |
| `sources` | `{"sources": [...]}` | Ranked source list |
| `done` | `{"finished": true}` | Loop complete |
| `error` | `{"message": "...", ...}` | Non-fatal error |

### Example stream

```jsonl
{"type": "init", "data": {"query": "what is HTTP/3", "mode": "balanced"}}
{"type": "plan", "data": {"plan": "Search for HTTP/3 overview and RFC"}}
{"type": "search", "data": {"queries": ["HTTP/3 overview", "HTTP/3 RFC 9114"]}}
{"type": "search_results", "data": {"count": 8}}
{"type": "response", "data": {"delta": "HTTP/3 is the third major version"}}
{"type": "response", "data": {"delta": " of the Hypertext Transfer Protocol [1]."}}
{"type": "sources", "data": {"sources": [{"url": "https://...", "title": "..."}]}}
{"type": "done", "data": {"finished": true}}
```

### Source object shape

```jsonc
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "content": "Extracted text snippet...",
  "similarity": 0.87   // embedding similarity score
}
```

## Combining `--stream` and `-o`

When both flags are given, NDJSON events go to stdout and the final
synthesized markdown (synthesis + references) is written to the file.
The file is written after the `done` event.
