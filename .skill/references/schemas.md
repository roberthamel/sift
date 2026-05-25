# sift JSON output schemas

## sift search output

```jsonc
{
  "query": "linux",
  "engines_used": ["wikipedia", "duckduckgo"],
  "results": [
    {
      "title": "Linux",
      "url": "https://en.wikipedia.org/wiki/Linux",
      "content": "Linux is a family of open-source Unix-like operating systems...",
      "engine": "wikipedia",
      "score": 1.0,
      "category": "general"
    }
  ],
  "answers": [],
  "infoboxes": [],
  "suggestions": [],
  "corrections": [],
  "unresponsive_engines": [
    { "engine": "name", "error_type": "timeout" }
  ],
  "number_of_results": 1,
  "elapsed_seconds": 0.84
}
```

**Notes:**
- Empty collections are always `[]` — never omitted, never `null`
- `error_type` on unresponsive engines: one of `timeout`, `http_error`, `network`, `filter_failed`, `invalid_url`

### With `--fetch` (inline fetch)

Additional fields on each result:

```jsonc
{
  // ... standard result fields
  "markdown": "# Linux\n\n... full page markdown ...",
  "filter": "fit"  // the filter that was used
}
```

Unfetched results get `"markdown": null, "filter": null`. A top-level `fetch_errors[]` is always present when `--fetch` is used.

### With `--summary`

```jsonc
{
  // ... standard search + fetch fields
  "summary": "The CFS scheduler ... [1] ... [2] ...",
  "model": "llama3:8b",
  "llm_error": null  // or string if LLM failed
}
```

When LLM fails: `"summary": null, "llm_error": "LLM not configured: missing --llm-host (or SIFT_LLM_HOST)"`

---

## sift fetch output

```jsonc
{
  "results": [
    {
      "url": "https://example.com",
      "markdown": "# Example Domain\n...",
      "filter": "fit"
      // When piped from search, also:
      // "title": "...",
      // "engine": "...",
      // "score": 1.0,
      // "category": "general",
      // "content": "..."
    }
  ],
  "fetch_errors": [
    { "url": "...", "error_type": "timeout", "message": "timed out" }
  ],
  "elapsed_seconds": 1.23
}
```

### With `--prompt`

```jsonc
{
  "results": [
    {
      "url": "https://example.com",
      "markdown": "# Example Domain\n...",
      "filter": "fit",
      "processed_markdown": "Author: ...\nDate: ...\nKey claims: ...",
      "llm_error": null
    }
  ],
  "fetch_errors": [],
  "elapsed_seconds": 1.23
}
```

**Notes:**
- `processed_markdown` only present when `--prompt` is used
- `llm_error` only present when the per-page LLM pass failed
- `error_type`: one of `timeout`, `http_error`, `network`, `filter_failed`, `invalid_url`

---

## sift synthesize output

```jsonc
{
  "query": "explain the CFS scheduler",
  "summary": "The CFS scheduler ... [1] ... [2] ...",
  "source_count": 5,
  "snippet_only": false,
  "model": "llama3:8b"
}
```

**Notes:**
- `snippet_only: true` when no fetched content was available (only search snippets)
- On LLM failure: `"summary": null, "llm_error": "..."` — exit code is still 0
- When piped sources had fetch errors: `"source_errors": [{"url": "...", "error": "..."}]`

---

## sift describe output

```jsonc
{
  "source": "./photo.jpg",
  "mime": "image/jpeg",
  "bytes": 124513,
  "success": true,
  "description": "A close-up of a red bicycle...",
  "model": "qwen2.5vl:7b"
}
```

On failure:

```jsonc
{
  "source": "./photo.jpg",
  "success": false,
  "error": "unrecognized image format (expected PNG/JPEG/GIF/WebP)"
}
```

---

## sift cache output

### `cache stats`

```jsonc
{
  "root": "/Users/rh/.cache/sift",
  "entries": 12,
  "bytes": 48213
}
```

### `cache clear`

```jsonc
{ "removed": 12 }
```

---

## sift research output

### Default JSON mode

```jsonc
{
  "query": "tenacity vs avoidance",
  "mode": "balanced",
  "actions": [
    {
      "name": "plan",
      "args": { "plan": "Searching for comparisons..." },
      "type": "plan_reasoning",
      "data": { "plan": "Searching for comparisons..." }
    },
    {
      "name": "search",
      "args": { "queries": ["tenacity vs avoidance python comparison", ...] },
      "type": "search_results",
      "data": {
        "results": [
          {
            "url": "https://example.com",
            "title": "Comparison",
            "content": "full content or snippet",
            "similarity": 0.89
          }
        ]
      }
    }
  ],
  "sources": [
    {
      "url": "https://example.com",
      "title": "Comparison",
      "content": "deduped merged content",
      "similarity": 0.89
    }
  ],
  "synthesis": "# Comparison\n\nTenacity and avoidance... [1] ... [2] ...",
  "usage": { "prompt": 1234, "completion": 567, "total": 1801 },
  "errors": []
}
```

### Stream mode (NDJSON)

One JSON object per line, each with `type` and `data`:

```jsonc
{"type": "init", "data": {"query": "...", "mode": "balanced", "max_iter": 6}}
{"type": "plan", "data": {"plan": "Searching for..."}}
{"type": "search", "data": {"queries": ["q1", "q2"]}}
{"type": "search_results", "data": {"count": 15, "queries": ["q1", "q2"]}}
{"type": "reading", "data": {"urls": ["https://..."]}}
{"type": "extracted", "data": {"url": "https://...", "facts": "..."}}
{"type": "response", "data": {"delta": "The CFS scheduler..."}}  // incremental writer output
{"type": "sources", "data": {"sources": [...]}}
{"type": "done", "data": {"finished": true, "iters": 4}}
{"type": "error", "data": {"stage": "search", "query": "q", "error": "..."}}
```

### TUI mode

Renders in the terminal using Rich. Shows:
- Action log (plan, search, results, reading, extracted, errors, done)
- Live-updating markdown synthesis
- Follow-up REPL after research completes
