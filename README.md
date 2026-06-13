# sift

A command-line research tool that runs a **Vane-style multi-step research loop** entirely
in-process: plan → search (via SearXNG) → embed-rank → (optionally scrape via crawl4ai) → synthesize.

- No Flask server, no port bound, no Redis, no multi-user state.
- Bundled minimal `settings.yml` with the default-enabled engines.
- All logs are written to a rotating file (default
  `$XDG_STATE_HOME/sift/sift.log`); stdout is reserved for
  the result.

## Install

```sh
curl -LsSf https://raw.githubusercontent.com/roberthamel/sift/main/install.sh | bash
```

Checks for [uv](https://astral.sh/uv), installs it if missing, then runs
`uv tool install`. Installs `sift` into `~/.local/bin` (or wherever
`uv tool` puts binaries on your system).

**Manual / local checkout:**

```sh
cd sift
uv sync
uv run sift --help   # no install needed, runs from the checkout
```

## Usage

Every research session is automatically saved as a markdown file under
`<base>/<scope>/`, where the base directory defaults to `~/.sift` and is
configurable via `storage.base_dir` (or `SIFT_STORAGE_BASE_DIR`). The LLM picks
a topical folder name and filename — first as a best guess from the opening
question, then refined once the research is done to reflect what was actually
found.

```sh
# Interactive REPL — prompts for the first question, then loops until Ctrl-D
sift

# REPL seeded with a first question
sift "give me an introduction to Viper in a Golang CLI"

# Non-interactive: research once, print answer to stdout, save to file, exit
sift --print "what is HTTP/3"

# Continue an existing research document (preloads it as context)
sift --continue ~/.sift/golang/viper-config-library.md
sift --continue ~/.sift/golang/viper-config-library.md "how does it handle env vars?"

# Emit NDJSON events for programmatic consumption
sift --stream "what is HTTP/3"
```

### Follow-up REPL

After the first turn, `sift` drops into a follow-up prompt (`>`).

- Type a **follow-up question** to run another research turn — new findings are
  **merged** into the existing document.
- Type **`/new`** to reset the session and start a fresh research document.
- Press **Ctrl-D** (EOF) to exit.
- A blank line re-prompts (does not exit).

### Auto-save and document lifecycle

Each turn's synthesized answer is written to `<base>/<scope>/<filename>.md`
(base defaults to `~/.sift`). The scope and filename are chosen by the LLM — an
initial guess from the opening question, then corrected after research based on
the findings (e.g. `golang/viper-config-library.md`). If the file already exists,
a numeric suffix is appended (`-2`, `-3`, …) — existing files are never clobbered.

Follow-up turns **merge** new findings into the same file rather than replacing it.
The document grows and stays coherent across the whole conversation.

Every saved file includes YAML frontmatter:

```markdown
---
queries:
  - give me an introduction to Viper in a Golang CLI
  - how does it handle environment variables?
created: 2025-06-01T14:22:10Z
updated: 2025-06-01T14:28:44Z
turns: 2
---

## Introduction to Viper
…
```

`--continue <path>` reopens a saved document: its content becomes pre-context for the
researcher (informing what new searches to run) and the writer (merging new findings
into the existing text). The same file is updated in place.

### All options

| Flag | Default | Env var | Notes |
| --- | --- | --- | --- |
| `QUERY` (positional) | (prompt if omitted) | — | Research question |
| `--mode {speed,balanced,quality}` | `balanced` | — | Research depth |
| `--print / -p` | off | — | Non-interactive: print answer to stdout and exit |
| `--continue / -c PATH` | (none) | — | Continue an existing research document |
| `--stream` | off | — | Emit NDJSON events to stdout |
| `--llm-host URL` | — | `SIFT_LLM_HOST` | OpenAI-compatible base URL |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` | Use `-` for local endpoints |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` | Model identifier |
| `--embed-base-url URL` | — | `SIFT_EMBED_BASE_URL` | Embedding endpoint |
| `--embed-api-key KEY` | — | `SIFT_EMBED_API_KEY` | — |
| `--embed-model NAME` | — | `SIFT_EMBED_MODEL` | Embedding model |
| `--system STR` | (none) | — | System instructions injected into the writer prompt |
| `--history-file PATH` | (none) | — | JSON file `[[role, text], ...]` |
| `--lang all` | `all` | — | BCP-47-ish; `all`/`auto` accepted |
| `--safesearch 0` | `0` | — | `0`, `1`, `2` |
| `--allow DOMAIN` | (none) | — | Repeatable; keep URLs whose host ends in this suffix |
| `--block DOMAIN` | (none) | — | Repeatable; drop URLs whose host ends in this suffix |
| `--settings PATH` | bundled `data/settings.yml` | `SEARXNG_SETTINGS_PATH` | Override SearXNG settings file |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | — | Rotated, 1 MB × 3 |
| `--verbose` | off | — | Raises file log level to DEBUG |
| `--config` | — | — | Manage the config file (see below) instead of researching |

### Timeout env vars

| Variable | Default | Applies to |
| --- | --- | --- |
| `SIFT_LLM_TIMEOUT` | `3600` (1 hour) | LLM API calls (research loop, writer) |
| `SIFT_EMBED_TIMEOUT` | `600` (10 min) | Embedding API calls |

### Configuration file

Persist settings in `~/.config/sift/config.yaml` (honors `$XDG_CONFIG_HOME`) so
you don't have to export env vars every session. Values resolve with the
precedence **CLI flag → environment variable → config file → built-in default**,
so env vars still override the file.

| Command | Effect |
| --- | --- |
| `sift --config` | Show the effective config and where each value came from |
| `sift --config --init` | Write a commented template and open it in `$EDITOR` (`--force` to overwrite) |
| `sift --config --edit` | Open the existing config file in `$EDITOR` |
| `sift --config <key>` | Print the resolved value for a key (e.g. `sift --config llm.model`) |
| `sift --config <key>=<value>` | Set a value (e.g. `sift --config llm.model=gpt-x`) |

Supported keys: `llm.host`, `llm.api_key`, `llm.model`, `llm.vlm`, `llm.timeout`,
`embed.base_url`, `embed.api_key`, `embed.model`, `embed.timeout`,
`storage.base_dir` (base directory for saved research, default `~/.sift`, env
`SIFT_STORAGE_BASE_DIR`). API keys are masked when displayed.

### Research modes

| Mode | Max iterations | Behavior |
| --- | --- | --- |
| `speed` | 2 | Direct search, no planning step, no scrape |
| `balanced` | 6 | Plan → search (embed-ranked) → done |
| `quality` | 25 | Plan → search → LLM-pick best → scrape → chunk → extract facts → repeat |

### NDJSON events (`--stream`)

One JSON object per line. Full list of event types:

| Type | `data` fields | Notes |
| --- | --- | --- |
| `init` | `{"query": "...", "mode": "...", "max_iter": N}` | First event emitted |
| `plan` | `{"plan": "..."}` | LLM's research plan (full text) |
| `search` | `{"queries": ["q1", "q2"]}` | Search queries issued |
| `search_query` | `{"query": "...", "status": "running"|"done"|"failed"}` | Per-query progress |
| `search_results` | `{"count": N}` | Results returned |
| `reading` | `{"urls": ["..."]}` | URLs being scraped |
| `fetch_url` | `{"url": "...", "status": "fetching"|"done"|"failed"}` | Per-URL fetch progress |
| `extracted` | `{"url": "..."}` | URL content extracted |
| `iter_progress` | `{"iter": N, "max_iter": N}` | Loop iteration progress |
| `response` | `{"delta": "..."}` | Streaming answer chunk — concatenate for full synthesis |
| `sources` | `{"sources": [...]}` | Ranked source list (URL, title, content, similarity) |
| `done` | `{"finished": true}` | Research loop complete |
| `error` | `{"message": "...", ...}` | Non-fatal error |

`--stream` is composable with `--print` for non-interactive scripted use.

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
| `0` | Success (REPL exited cleanly, or `--print`/`--stream` produced a result) |
| `1` | No synthesis produced |
| `2` | Bad invocation (missing question with `--print`, unknown `--mode`, LLM/embed not configured, bad history file, `--continue` file not found) |

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

## Testing

```sh
uv run pytest
```

Tests are in `tests/` and use pytest. The test suite includes unit tests for the
research loop, writer, actions, embeddings, persistence, TUI, domain filters, and
CLI help output.

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE). Matches upstream SearXNG.
