# sift

A Typer-based command-line interface that runs **SearXNG** searches and
**crawl4ai** page-fetches **in-process** and prints LLM-friendly JSON to
stdout. Search the web, then sift the readable text out of the results —
all from one shell pipeline.

- No Flask server, no port bound, no Redis, no multi-user state.
- Bundled minimal `settings.yml` with the default-enabled engines.
- All logs are written to a rotating file (default
  `$XDG_STATE_HOME/sift/sift.log`); stdout is reserved for
  the result.

## Install

```sh
uv tool install git+https://<your-public-repo-url>
```

During development, from a checkout that has `searxng` as a sibling
directory:

```sh
cd sift
uv sync
uv run sift --help
```

## Usage

```sh
sift search "your query"
sift search "linux" --engines duckduckgo,wikipedia
sift search "linux" --category it --page 2
sift search "linux" --pretty             # human-readable text
```

### All options

| Flag | Default | Notes |
| --- | --- | --- |
| `--engines a,b,c` | (all enabled for category) | comma-separated engine names |
| `--category general` | `general` | must match a category in settings |
| `--page 1` | `1` | |
| `--lang all` | `all` | BCP-47-ish; `all`/`auto` accepted |
| `--safesearch 0` | `0` | `0`, `1`, `2` |
| `--timeout 5.0` | (engine default) | hard limit in seconds |
| `--settings PATH` | bundled `data/settings.yml` | overrides `$SEARXNG_SETTINGS_PATH` |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | rotated, 1 MB × 3 |
| `--verbose` | off | raises file log level to DEBUG |
| `--pretty` | off | numbered text instead of JSON |

## JSON output schema

```jsonc
{
  "query": "linux",
  "engines_used": ["wikipedia"],
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

Empty collections are always present as `[]` — never omitted, never `null`.

## `fetch` — full-text via crawl4ai

`sift fetch` runs result URLs through [crawl4ai](https://github.com/unclecode/crawl4ai)
**in-process** (no Docker, no port) and returns the readable page body
("fit markdown") for each URL.

```sh
# URLs as args
sift fetch https://en.wikipedia.org/wiki/Linux

# URL list on stdin (blank lines and `# comments` are ignored)
echo "https://example.com" | sift fetch

# Pipe straight from a search
sift search "linux" --engines wikipedia | sift fetch
```

When stdin is the JSON output of `search`, the original `title`, `engine`,
`score`, `category`, and `content` (snippet) fields flow through alongside
the new `markdown` and `filter` fields per result.

### Inline fetch on `search`

```sh
sift search "linux" --engines wikipedia --fetch --fetch-top 3
```

Embeds `markdown` and `filter` directly into the existing `results[]`. Items
beyond `--fetch-top` get `markdown: null`. A top-level `fetch_errors[]` is
always added when `--fetch` is set.

### `fetch` options

| Flag | Default | Notes |
| --- | --- | --- |
| `--concurrency N` | `5` | parallel fetches |
| `--timeout SECONDS` | `20.0` | per-URL timeout |
| `--filter {fit,raw,bm25,llm}` | `fit` | `fit` = PruningContentFilter (readability) |
| `--query STR` | _(none)_ | required for `bm25`/`llm`; for `search --fetch` defaults to the search query |
| `--pretty` | off | human-readable instead of JSON |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | rotated, 1 MB × 3 |
| `--verbose` | off | raises file log level to DEBUG |

A **hard cap of 50 URLs per invocation** is enforced. Exceeding it exits
non-zero with a usage error — crawl4ai is not imported in that case.

### `fetch` JSON output schema

```jsonc
{
  "results": [
    {
      "url": "https://example.com",
      "markdown": "# Example Domain\n...",
      "filter": "fit"
      // plus title/engine/score/category/content when piped from `search`
    }
  ],
  "fetch_errors": [
    { "url": "...", "error_type": "timeout", "message": "timed out" }
  ],
  "elapsed_seconds": 1.23
}
```

`error_type` is one of `timeout`, `http_error`, `network`, `filter_failed`,
`invalid_url`.

### `fetch` exit codes

- `0` — at least one URL produced markdown
- `1` — every URL failed
- `2` — no URLs supplied, hard cap exceeded, or invalid filter/query combo
- `3` — `crawl4ai` package not importable

`search --fetch` never demotes the exit code on fetch failures; failed URLs
appear in `fetch_errors[]`.

### Live smoke (requires crawl4ai browser bundle)

```sh
SEARXNG_CLI_LIVE_CRAWL=1 uv run pytest -k live
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success (even if `results` is empty) |
| `1` | user error (unknown engine, bad flag, malformed query) |
| `2` | internal error (initialization failed, all engines unresponsive) |

## Log file

All logs from `searx.*` and `sift` are routed to a rotating file
handler so that **stdout stays a single JSON document**. The default
location follows the XDG Base Directory spec:
`$XDG_STATE_HOME/sift/sift.log`, falling back to
`~/.local/state/sift/sift.log`. Override with `--log-file`.

## Smoke test

```sh
uv run sift search "site:wikipedia.org Linux" --engines wikipedia \
  | jq '.results | length'   # → ≥ 1
```

## Non-goals

- **Not a server.** Never binds a port, never imports `searx.webapp`.
- **Not multi-user.** No request context, no preferences, no plugin storage.
- **Not a SearXNG fork.** Pins `searxng` as a dependency; if upstream
  renames an engine or changes the result-container API, update the pin.

## License

AGPL-3.0-or-later (matches upstream SearXNG).
