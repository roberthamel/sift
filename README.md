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

From a public repo:

```sh
uv tool install git+https://<your-public-repo-url>
```

From a local checkout (the supported path while `searxng` and `crawl4ai`
are pinned as sibling editable sources):

```sh
cd sift
./install.sh                       # → ~/.local/bin/sift (default)
./install.sh ~/bin/sift             # or a custom target
```

`install.sh` runs `uv sync` to build the project venv and drops a thin
wrapper on your PATH that delegates to `uv run --project <repo>`. Edits to
`src/sift/*.py` take effect on the next invocation — no reinstall step.

If you'd rather not install on PATH, you can always invoke through uv:

```sh
cd sift && uv sync
uv run sift --help
```

`uv tool install -e .` is **not** recommended for this stack: it doesn't
honor the project's `[tool.uv].override-dependencies` or
`[tool.uv.extra-build-dependencies]`, both of which are load-bearing here.
Specifically:

- `crawl4ai` pins `lxml<6` and `searxng` pins `lxml==6.1.1`. The project
  workspace overrides `lxml==6.1.1`; without that override the resolver
  fails.
- `searxng`'s build process imports `msgspec`, but `msgspec` isn't in
  `searxng`'s `build-system.requires`. The project workspace adds the
  missing build deps via `[tool.uv.extra-build-dependencies]`. `uv tool
  install` skips that section and the build blows up.

The wrapper-script approach sidesteps both by reusing the project's
already-correct `uv sync` environment.

For a hermetic dev loop without installing on PATH:

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

A **hard cap of 100 URLs per invocation** is enforced. Exceeding it exits
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

## LLM features

sift is the successor to [`websearch-mcp`](https://github.com/<user>/websearch-mcp):
the same OpenAI-compatible LLM/VLM features, exposed as composable CLI stages
instead of MCP tools. There is no config file — every LLM-touching command
takes the same flag bundle (with `SIFT_LLM_*` env vars as fallbacks):

| Flag | Env var | Notes |
| --- | --- | --- |
| `--llm-host URL` | `SIFT_LLM_HOST` | OpenAI-compatible base URL, e.g. `http://localhost:11434/v1` |
| `--llm-apikey KEY` | `SIFT_LLM_APIKEY` | use `-` for local endpoints that don't authenticate |
| `--llm-model NAME` | `SIFT_LLM_MODEL` | model identifier the endpoint exposes |
| `--vlm` | `SIFT_VLM=1` | per-invocation assertion that the configured model has vision; required by `describe` |

LLM failures are **soft** for `search --summary` and `sift synthesize`: the
search/fetch payload is still emitted, with `summary: null` and a
`llm_error` string. Exit code is `0`. `sift describe` likewise exits `0` on
LLM failure with `success: false`. Hard exit code `2` is reserved for
missing/invalid LLM config.

### `synthesize` — cited summary from piped sources

```sh
sift search "linux kernel scheduler" --fetch --fetch-top 5 \
  | sift synthesize "explain the CFS scheduler"
```

Reads search-JSON **or** fetch-JSON on stdin. When only `content` (snippet)
is present, the output carries `snippet_only: true` so callers can see the
model was working from synopses.

```jsonc
{
  "query": "explain the CFS scheduler",
  "summary": "The CFS scheduler ... [1] ... [2] ...",
  "source_count": 5,
  "snippet_only": false,
  "model": "llama3:8b"
}
```

### `search --summary` — one-shot search → fetch → synthesize

```sh
sift search "what is HTTP/3" --summary
```

Chains the same pipeline in a single invocation. Same LLM flags as above.

### `search --allow / --block` — domain filters

Repeatable. Suffix-match against the URL host (so `wikipedia.org` matches
`en.wikipedia.org` but **not** `notwikipedia.org`):

```sh
sift search "python releases" --allow python.org --allow wikipedia.org
sift search "open source" --block reddit.com --block twitter.com
```

`--allow` is applied first (inclusion); `--block` then excludes from the
result.

### `fetch --prompt` — per-page LLM pass

After crawl4ai produces page markdown, run an additional LLM pass over each
result. Raw `markdown` is preserved; the LLM's output is attached as
`processed_markdown`:

```sh
sift fetch https://example.com/article --prompt "extract author, date, key claims"
```

This is **independent** of `--filter llm`: the filter shapes what
crawl4ai extracts; `--prompt` runs after extraction on whatever markdown
came out.

### `describe` — image description via VLM

```sh
sift describe ./photo.jpg --vlm
sift describe "data:image/png;base64,..." --vlm
sift describe "https://example.com/img.png" --vlm
sift describe "<base64 string>" --vlm
```

Accepts a file path, http(s) URL, data URL, or raw base64. Format validation
is via magic bytes (PNG, JPEG, GIF, WebP). A 10 MB default cap is enforced
(`--max-bytes`).

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

### Cache

sift maintains an on-disk cache at `$XDG_CACHE_HOME/sift/`. `search`
responses are cached by default; pass `--no-cache` to bypass, `--cache-ttl 0`
to keep entries forever, or use the `cache` subcommand:

```sh
sift cache stats          # { "root": "...", "entries": 12, "bytes": 48213 }
sift cache clear          # { "removed": 12 }
```

## Migration from `websearch-mcp`

The MCP server is deprecated. The mapping is:

| websearch-mcp tool | sift equivalent |
| --- | --- |
| `web_search` | `sift search` (plus `--summary`, `--allow`, `--block`) |
| `webfetch` | `sift fetch` (plus `--prompt`) |
| `synthesize_search_results` | `sift synthesize` |
| `image_description` | `sift describe --vlm` |

Once you've cut over, **archive the `websearch-mcp` repo** on GitHub — this
step is manual.

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
