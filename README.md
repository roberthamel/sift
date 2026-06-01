# sift

A command-line research tool that runs a **Vane-style multi-step research loop** entirely
in-process: plan → search (via SearXNG) → embed-rank → scrape (via crawl4ai) → synthesize.

- No Flask server, no port bound, no Redis, no multi-user state.
- Bundled minimal `settings.yml` with the default-enabled engines.
- All logs are written to a rotating file (default
  `$XDG_STATE_HOME/sift/sift.log`); stdout is reserved for
  the result.

## Install

```sh
curl -LsSf https://raw.githubusercontent.com/roberthamel/sift/main/install.sh | sh
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
`.ai/research/<scope>/` in the current directory. The LLM picks a topical
folder name and filename from the opening question.

```sh
# Interactive REPL — prompts for the first question, then loops until Ctrl-D
sift

# REPL seeded with a first question
sift "give me an introduction to Viper in a Golang CLI"

# Non-interactive: research once, print answer to stdout, save to file, exit
sift --print "what is HTTP/3"

# Continue an existing research document (preloads it as context)
sift --continue .ai/research/golang/viper-config-library.md
sift --continue .ai/research/golang/viper-config-library.md "how does it handle env vars?"

# Emit NDJSON events for programmatic consumption
sift --stream "what is HTTP/3"
```

### Auto-save and document lifecycle

Each turn's synthesized answer is written to `.ai/research/<scope>/<filename>.md`.
The scope and filename are chosen by the LLM from the opening question (e.g.
`golang/viper-config-library.md`). If the file already exists, a numeric suffix is
appended (`-2`, `-3`, …) — existing files are never clobbered.

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

`response` events carry `{"delta": "..."}` chunks that concatenate to the full
synthesis. `sources` carries the ranked source list. `--stream` is composable
with `--print` for non-interactive scripted use.

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

## License

AGPL-3.0-or-later — see [LICENSE](LICENSE). Matches upstream SearXNG.
