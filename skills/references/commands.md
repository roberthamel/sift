# sift commands — full reference

## sift search

Run a SearXNG search in-process and print JSON results to stdout.

### Flags

| Flag | Default | Env var | Notes |
|------|---------|---------|-------|
| `query` (positional, required) | — | — | Search query string |
| `--engines a,b,c` | (all enabled for category) | — | Comma-separated engine names |
| `--category general` | `general` | — | Must match a category in settings.yml |
| `--page 1` | `1` | — | Page number |
| `--lang all` | `all` | — | BCP-47-ish; `all`/`auto` accepted |
| `--safesearch 0` | `0` | — | `0`, `1`, `2` |
| `--timeout SECONDS` | (engine default) | — | Hard limit in seconds |
| `--settings PATH` | bundled `data/settings.yml` | `SEARXNG_SETTINGS_PATH` | Override settings file |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | — | Rotating file, 1 MB × 3 |
| `--verbose` | off | — | Raises file log level to DEBUG |
| `--pretty` | off | — | Human-readable text instead of JSON |
| `--fetch` | off | — | Also fetch markdown for top results |
| `--fetch-top N` | `10` | — | How many results to fetch (0 = all, capped at 100) |
| `--concurrency N` | `5` | — | Parallel fetches |
| `--timeout-fetch SECONDS` | `20.0` | — | Per-URL fetch timeout |
| `--filter {fit,raw,bm25,llm}` | `fit` | — | Content filter for crawl4ai |
| `--query STR` | (search query) | — | Filter query for bm25/llm |
| `--allow DOMAIN` | (none) | — | Repeatable; keep URLs whose host ends in this suffix |
| `--block DOMAIN` | (none) | — | Repeatable; drop URLs whose host ends in this suffix |
| `--summary` | off | — | After fetch, run LLM synthesis and attach `summary` |
| `--llm-host URL` | — | `SIFT_LLM_HOST` | OpenAI-compatible base URL |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` | Use `-` for local endpoints |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` | Model identifier |
| `--cache-ttl SECONDS` | `3600` | — | TTL for cached entries (0 = never expire) |
| `--no-cache` | off | — | Bypass cache entirely |

### Domain filter behavior

`--allow` is applied first (inclusion), then `--block` excludes. Suffix match: `wikipedia.org` matches `en.wikipedia.org` and itself, but NOT `notwikipedia.org`.

### Examples

```sh
# Basic search
sift search "linux kernel scheduler"

# Specific engines
sift search "linux" --engines duckduckgo,wikipedia

# Category and page
sift search "linux" --category it --page 2

# Human-readable output
sift search "linux" --pretty

# Fetch top 3 results with custom filter
sift search "HTTP/3" --fetch --fetch-top 3 --filter bm25

# Domain filtering
sift search "python releases" --allow python.org --allow wikipedia.org
sift search "open source" --block reddit.com --block twitter.com

# One-shot synthesis
sift search "what is HTTP/3" --summary
```

---

## sift fetch

Fetch full-page markdown for URLs via crawl4ai (in-process). URLs from positional args, stdin (one per line, `#` comments), or piped search JSON.

### Flags

| Flag | Default | Notes |
|------|---------|-------|
| `urls` (positional) | (read from stdin) | URLs to fetch |
| `--concurrency N` | `5` | Parallel fetches |
| `--timeout SECONDS` | `20.0` | Per-URL timeout |
| `--filter {fit,raw,bm25,llm}` | `fit` | Content filter |
| `--query STR` | (none) | Required for `bm25`/`llm` filters |
| `--prompt STR` | (none) | Post-extraction LLM pass; attaches `processed_markdown` |
| `--llm-host URL` | — | `SIFT_LLM_HOST` fallback |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` fallback |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` fallback |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | Rotating file |
| `--verbose` | off | Raises file log level |
| `--pretty` | off | Human-readable instead of JSON |
| `--settings PATH` | bundled | Kept for parity |

### Hard cap

Maximum **100 URLs** per invocation. Exceeding it exits with code 2.

### Examples

```sh
# Fetch URLs from arguments
sift fetch https://en.wikipedia.org/wiki/Linux

# Pipe from search
sift search "linux" --engines wikipedia | sift fetch

# URL list on stdin (blank lines and # comments are ignored)
echo "https://example.com" | sift fetch

# With per-page LLM prompt
sift fetch https://example.com/article --prompt "extract author, date, key claims"

# Custom filter with query
sift fetch https://example.com --filter bm25 --query "my topic"
```

### stdin input shapes

1. **Search JSON** from `sift search` — extracts URLs from `results[].url`, passes through `title`, `engine`, `score`, `category`, `content` fields.
2. **Raw URL list** — one URL per line, blank lines and `#`-prefixed comments ignored.
3. **Empty / TTY** — no URLs produced.

---

## sift synthesize

LLM-synthesize a cited summary from piped search/fetch JSON on stdin.

### Arguments

| Argument | Required | Notes |
|----------|----------|-------|
| `query` | Yes | The question the LLM should answer using piped sources |

### Flags

Same LLM bundle: `--llm-host`, `--llm-apikey`, `--llm-model`. Plus `--pretty`.

### stdin shapes

1. **Search JSON**: `{"query": ..., "results": [{title,url,content,engine,...}]}` — each result may carry `markdown` (from `--fetch`) or `processed_markdown` (from `--prompt`). Content precedence: `processed_markdown` > `markdown` > `content`. When only `content` (snippet) is present, output carries `snippet_only: true`.
2. **Fetch JSON**: `{"results": [{url, markdown, ...}], "fetch_errors": [...]}`.

### Examples

```sh
sift search "linux kernel scheduler" --fetch --fetch-top 5 \
  | sift synthesize "explain the CFS scheduler"

# Snippet-only mode (no --fetch)
sift search "linux kernel scheduler" \
  | sift synthesize "explain the CFS scheduler"
```

---

## sift describe

Describe an image via a vision-capable LLM. Accepts four input shapes:

1. **File path**: `./photo.jpg`
2. **HTTP(S) URL**: `https://example.com/img.png`
3. **Data URL**: `data:image/png;base64,...`
4. **Raw base64**: `<base64 string>`

### Flags

| Flag | Default | Notes |
|------|---------|-------|
| `image` (positional, required) | — | Path, URL, data URL, or base64 |
| `--prompt STR` | (none) | Custom prompt for the VLM |
| `--max-bytes N` | `10485760` (10 MB) | Reject images larger than this |
| `--vlm` | off | **Required** — asserts model has vision capabilities |
| `--llm-host URL` | — | `SIFT_LLM_HOST` fallback |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` fallback |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` fallback |
| `--pretty` | off | Human-readable |

### Format validation

By magic bytes (PNG, JPEG, GIF, WebP), not file extension. Unrecognized formats are rejected with exit code 1.

### Examples

```sh
sift describe ./photo.jpg --vlm
sift describe "data:image/png;base64,iVBOR..." --vlm
sift describe "https://example.com/img.png" --vlm
```

---

## sift cache

Inspect or clear sift's on-disk cache at `$XDG_CACHE_HOME/sift/`.

### Subcommands

```sh
sift cache stats   # → {"root": "...", "entries": 12, "bytes": 48213}
sift cache clear   # → {"removed": 12}
```

---

## sift research

Vane-style deep research loop: plan → search → embed → scrape → extract → write synthesis. Runs entirely in-process.

### Arguments

| Argument | Required | Notes |
|----------|----------|-------|
| `query` | Yes (no with `--tui`) | The research question; optional when using the interactive TUI |

### Flags

| Flag | Default | Env var | Notes |
|------|---------|---------|-------|
| `--mode {speed,balanced,quality}` | `balanced` | — | Research depth |
| `--llm-host URL` | — | `SIFT_LLM_HOST` | For planning, extraction, writing |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` | — |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` | — |
| `--embed-base-url URL` | — | `SIFT_EMBED_BASE_URL` | For snippet ranking (required) |
| `--embed-api-key KEY` | — | `SIFT_EMBED_API_KEY` | — |
| `--embed-model NAME` | — | `SIFT_EMBED_MODEL` | — |
| `--system STR` | (none) | — | System instructions injected into writer prompt |
| `--history-file PATH` | (none) | — | JSON file shaped as `[[role, text], ...]` |
| `--stream` | off | — | Emit NDJSON events to stdout |
| `--output` / `-o` | (none) | — | Write synthesis to this markdown file |
| `--tui` | off | — | Rich Live TUI + follow-up REPL |
| `--lang` | `all` | — | Search language |
| `--safesearch 0-2` | `0` | — | Safe search level |
| `--allow DOMAIN` | (none) | — | Repeatable domain allow filter |
| `--block DOMAIN` | (none) | — | Repeatable domain block filter |
| `--log-file PATH` | default | — | Rotating file |
| `--verbose` | off | — | Raise log level |

### Modes

| Mode | Max iterations | Behavior |
|------|---------------|----------|
| `speed` | 2 | Direct search, no planning step, no scrape |
| `balanced` | 6 | Plan → search (embed-ranked) → done |
| `quality` | 25 | Plan → search → LLM-pick best → scrape → chunk → extract facts → repeat |

### Output modes

| Mode | What it produces |
|------|-----------------|
| Default (JSON) | Single JSON object with `actions[]`, `sources[]`, `synthesis`, `usage`, `errors[]` |
| `--stream` | NDJSON — one event per line: `{"type": "plan"\|"search"\|...`, `"data": {...}}` |
| `--tui` | Rich Live terminal UI with live markdown rendering, then follow-up REPL |

### Event types (stream mode)

`init`, `plan`, `search`, `search_results`, `reading`, `extracted`, `response`, `sources`, `done`, `error`

### Examples

```sh
# Basic research
sift research "tenacity vs avoidance in Python"

# Quality mode with custom system instructions
sift research "Rust async runtimes comparison" --mode quality

# Stream events for programmatic consumption
sift research "HTTP/3 benefits" --stream

# Interactive TUI mode
sift research "Kubernetes vs Nomad" --tui

# With conversation history
sift research "follow up" --history-file ./history.json
```

## Exit code reference

| Code | When | Notes |
|------|------|-------|
| `0` | Success | Even if results are empty |
| `1` | User error | Unknown engine, bad flag, all fetches failed, image error |
| `2` | Internal error | Init failed, LLM not configured, no stdin, bad history file |
| `3` | Dependency missing | crawl4ai not importable |

Special cases:
- `sift fetch`: code 1 when all URLs failed, code 2 when no URLs or hard cap exceeded
- `sift search --fetch`: never demotes exit code on fetch failures (errors in `fetch_errors[]`)
- `sift synthesize`: exits 0 even if LLM fails (error in `llm_error`)
- `sift describe`: exits 1 on image resolution error (bad format, too large)
