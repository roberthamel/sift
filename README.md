# sift

A command-line research tool that runs a **Vane-style multi-step research loop** entirely
in-process: plan → search (via SearXNG) → embed-rank → scrape (via crawl4ai) → synthesize.

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
# Interactive research TUI (follow-up REPL included)
sift

# One-shot research: live output, then exit
sift "what is HTTP/3"

# One-shot research + write answer to a file
sift -o ANSWER.md "what is HTTP/3"

# Emit NDJSON events for programmatic consumption
sift --stream "what is HTTP/3"
```

A question is required whenever `-o` is given. `sift -o file` with no
question exits non-zero with an error message.

### All options

| Flag | Default | Env var | Notes |
| --- | --- | --- | --- |
| `QUERY` (positional) | (prompt if omitted) | — | Research question |
| `--mode {speed,balanced,quality}` | `balanced` | — | Research depth |
| `--stream` | off | — | Emit NDJSON events to stdout |
| `-o / --output PATH` | (none) | — | Write synthesis markdown to file |
| `--llm-host URL` | — | `SIFT_LLM_HOST` | OpenAI-compatible base URL |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` | Use `-` for local endpoints |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` | Model identifier |
| `--embed-base-url URL` | — | `SIFT_EMBED_BASE_URL` | Embedding endpoint |
| `--embed-api-key KEY` | — | `SIFT_EMBED_API_KEY` | — |
| `--embed-model NAME` | — | `SIFT_EMBED_MODEL` | Embedding model |
| `--system STR` | (none) | — | System instructions for the writer |
| `--history-file PATH` | (none) | — | JSON file `[[role, text], ...]` |
| `--lang all` | `all` | — | BCP-47-ish; `all`/`auto` accepted |
| `--safesearch 0` | `0` | — | `0`, `1`, `2` |
| `--allow DOMAIN` | (none) | — | Repeatable; keep URLs whose host ends in this suffix |
| `--block DOMAIN` | (none) | — | Repeatable; drop URLs whose host ends in this suffix |
| `--settings PATH` | bundled `data/settings.yml` | — | Overrides `$SEARXNG_SETTINGS_PATH` |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | — | Rotated, 1 MB × 3 |
| `--verbose` | off | — | Raises file log level to DEBUG |

### Research modes

| Mode | Max iterations | Behavior |
| --- | --- | --- |
| `speed` | 2 | Direct search, no planning step, no scrape |
| `balanced` | 6 | Plan → search (embed-ranked) → done |
| `quality` | 25 | Plan → search → LLM-pick best → scrape → chunk → extract facts → repeat |

### NDJSON events (`--stream`)

One JSON object per line: `{"type": "plan"|"search"|"search_results"|"reading"|"extracted"|"response"|"sources"|"done"|"error", "data": {...}}`

`response` events carry `{"delta": "..."}` chunks that concatenate to the
full synthesis. `sources` carries the ranked source list. Combine `--stream`
with `-o` to get both the event stream and a clean markdown file.

## Domain filters

Repeatable `--allow` / `--block` use suffix matching against the URL host.
`wikipedia.org` matches `en.wikipedia.org` but not `notwikipedia.org`.
`--allow` is applied first (inclusion), then `--block` excludes.

```sh
sift --allow python.org --allow wikipedia.org "python releases"
sift --block reddit.com --block twitter.com "open source licenses"
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | No synthesis produced |
| `2` | Bad invocation (missing question with `-o`, unknown `--mode`, LLM/embed not configured, bad history file) |

## Log file

All logs from `searx.*` and `sift` are routed to a rotating file
handler. The default location follows the XDG Base Directory spec:
`$XDG_STATE_HOME/sift/sift.log`, falling back to
`~/.local/state/sift/sift.log`. Override with `--log-file`.

## Non-goals

- **Not a server.** Never binds a port, never imports `searx.webapp`.
- **Not multi-user.** No request context, no preferences, no plugin storage.
- **Not a SearXNG fork.** Pins `searxng` as a dependency; if upstream
  renames an engine or changes the result-container API, update the pin.

## License

AGPL-3.0-or-later (matches upstream SearXNG).
