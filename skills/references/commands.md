# sift command reference

## Usage

```
sift [OPTIONS] [QUERY]
```

`sift` is a **single command** — there are no subcommands. All options below
are research options.

## Arguments

| Argument | Required | Notes |
|----------|----------|-------|
| `QUERY` | No | Research question. Omit to be prompted interactively. |

## Options

| Flag | Default | Env var | Notes |
|------|---------|---------|-------|
| `--mode {speed,balanced,quality}` | `balanced` | — | Research depth |
| `--stream` | off | — | Emit NDJSON events to stdout |
| `-o / --output PATH` | (none) | — | Write synthesis to this markdown file |
| `--llm-host URL` | — | `SIFT_LLM_HOST` | OpenAI-compatible base URL |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` | Use `-` for local endpoints |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` | Model identifier |
| `--embed-base-url URL` | — | `SIFT_EMBED_BASE_URL` | Embedding endpoint (required) |
| `--embed-api-key KEY` | — | `SIFT_EMBED_API_KEY` | — |
| `--embed-model NAME` | — | `SIFT_EMBED_MODEL` | Embedding model (required) |
| `--system STR` | (none) | — | System instructions injected into writer prompt |
| `--history-file PATH` | (none) | — | JSON file `[[role, text], ...]` — prior conversation context |
| `--lang` | `all` | — | BCP-47-ish; `all`/`auto` accepted |
| `--safesearch 0-2` | `0` | — | Safe search level |
| `--allow DOMAIN` | (none) | — | Repeatable; keep only URLs whose host ends in this suffix |
| `--block DOMAIN` | (none) | — | Repeatable; drop URLs whose host ends in this suffix |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | — | Rotating file, 1 MB × 3 |
| `--verbose` | off | — | Raise file log level to DEBUG |
| `--settings PATH` | bundled `data/settings.yml` | — | Override SearXNG settings file |

## Domain filter behavior

`--allow` is applied first (inclusion), then `--block` excludes. Suffix match:
`wikipedia.org` matches `en.wikipedia.org` and itself, but NOT `notwikipedia.org`.

## Invocation forms

| Invocation | Behavior |
|------------|----------|
| `sift` | Prompt for question; run live TUI + follow-up REPL |
| `sift "q"` | Run once with live TUI output; exit (no REPL) |
| `sift -o file.md "q"` | Run once; write markdown to file; exit (no REPL) |
| `sift -o file.md` | **Error** (exit 2): question required when `-o` is given |
| `sift --stream "q"` | Emit NDJSON events to stdout; exit |

## Research modes

| Mode | Max iterations | Behavior |
|------|---------------|----------|
| `speed` | 2 | Direct search, no planning step, no scrape |
| `balanced` | 6 | Plan → search (embed-ranked) → done |
| `quality` | 25 | Plan → search → LLM-pick best → scrape → chunk → extract facts → repeat |

## Examples

```sh
# Interactive research with follow-up REPL
sift

# One-shot research question
sift "what is the CFS scheduler in Linux"

# Write answer to a file
sift -o answer.md "Rust async runtimes comparison"

# Quality mode with domain filters
sift --mode quality --allow wikipedia.org "explain mTLS"

# Stream events for programmatic use
sift --stream "HTTP/3 benefits"

# Combine stream with output file
sift --stream -o answer.md "what is WebAssembly"

# Custom system instructions
sift --system "Answer in bullet points" "best Python testing libraries"

# With conversation history for follow-ups
sift --history-file ./history.json "follow-up question"
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | No synthesis produced |
| `2` | Bad invocation: missing question with `-o`, unknown `--mode`, LLM/embed not configured, bad `--history-file` |
