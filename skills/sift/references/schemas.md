# sift output schemas

## Auto-save (all modes)

Every turn writes to `.ai/research/<scope>/<filename>.md` in the current directory.
The LLM picks scope and filename from the opening question. Files include YAML frontmatter:

```markdown
---
queries:
  - give me an intro to Viper in a Golang CLI
  - how does it handle environment variables?
created: 2025-06-01T14:22:10Z
updated: 2025-06-01T14:28:44Z
turns: 2
---

## Introduction to Viper

Viper is a configuration management library... [1]

## References

1. [Title](https://example.com)
```

- `queries` — all questions asked in this conversation, in order
- `created` — ISO timestamp of first save, never changed
- `updated` — refreshed on every save
- `turns` — cumulative count across sessions (preserved by --continue)

## --print output

`sift --print "q"` writes the synthesized answer (with inline citations and references)
to stdout. Same content as the auto-saved file body, without frontmatter.

## --stream NDJSON events

With `--stream`, one JSON object per line is written to stdout.

### Event types

| Type | `data` fields | Notes |
|------|--------------|-------|
| `init` | `{"query": "...", "mode": "..."}` | First event |
| `plan` | `{"plan": "..."}` | LLM-generated research plan (full text, not truncated) |
| `search` | `{"queries": ["q1", "q2"]}` | Search queries issued |
| `search_query` | `{"query": "...", "status": "running"|"done"|"failed"}` | Per-query status |
| `search_results` | `{"count": N}` | Results returned |
| `reading` | `{"urls": ["..."]}` | URLs being scraped |
| `fetch_url` | `{"url": "...", "status": "fetching"|"done"|"failed"}` | Per-URL status |
| `extracted` | `{"url": "..."}` | URL successfully extracted |
| `iter_progress` | `{"iter": N, "max_iter": N}` | Loop iteration progress |
| `response` | `{"delta": "..."}` | Streaming answer chunk |
| `sources` | `{"sources": [...]}` | Ranked source list |
| `done` | `{"finished": true}` | Loop complete |
| `error` | `{"message": "...", ...}` | Non-fatal error |

Concatenate all `response.delta` values for the full synthesis text.

### Example stream

```jsonl
{"type": "init", "data": {"query": "what is HTTP/3", "mode": "balanced"}}
{"type": "plan", "data": {"plan": "Search for HTTP/3 overview and RFC 9114"}}
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
  "similarity": 0.87
}
```
