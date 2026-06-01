# sift command reference

## Usage

```
sift [OPTIONS] [QUERY]
```

`sift` is a **single command** — there are no subcommands.

## Options

| Flag | Default | Env var | Notes |
|------|---------|---------|-------|
| `QUERY` (positional) | (prompt if omitted) | — | Research question |
| `--mode {speed,balanced,quality}` | `balanced` | — | Research depth |
| `--print / -p` | off | — | Non-interactive: print answer to stdout and exit |
| `--continue / -c PATH` | (none) | — | Continue an existing research document |
| `--stream` | off | — | Emit NDJSON events to stdout |
| `--llm-host URL` | — | `SIFT_LLM_HOST` | OpenAI-compatible base URL |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` | Use `-` for local endpoints |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` | Model identifier |
| `--embed-base-url URL` | — | `SIFT_EMBED_BASE_URL` | Embedding endpoint (required) |
| `--embed-api-key KEY` | — | `SIFT_EMBED_API_KEY` | — |
| `--embed-model NAME` | — | `SIFT_EMBED_MODEL` | Embedding model (required) |
| `--system STR` | (none) | — | System instructions injected into writer prompt |
| `--history-file PATH` | (none) | — | JSON file `[[role, text], ...]` |
| `--lang` | `all` | — | BCP-47-ish; `all`/`auto` accepted |
| `--safesearch 0-2` | `0` | — | Safe search level |
| `--allow DOMAIN` | (none) | — | Repeatable domain allow filter |
| `--block DOMAIN` | (none) | — | Repeatable domain block filter |
| `--log-file PATH` | `$XDG_STATE_HOME/sift/sift.log` | — | Rotating file, 1 MB x 3 |
| `--verbose` | off | — | Raise file log level to DEBUG |
| `--settings PATH` | bundled `data/settings.yml` | — | Override SearXNG settings file |

## Invocation forms

| Invocation | Behavior |
|------------|----------|
| `sift` | Prompt for question; run live TUI + follow-up REPL |
| `sift "q"` | Seed first turn with query; enter follow-up REPL |
| `sift --print "q"` | One turn, print answer to stdout, auto-save, exit |
| `sift --print` | Error (exit 2): query or --continue required |
| `sift --continue path` | Preload document; enter follow-up REPL |
| `sift --continue path "q"` | Preload document; first turn is query; enter REPL |
| `sift --print --continue path` | Refresh document in place, print answer, exit |
| `sift --stream "q"` | Emit NDJSON events to stdout; exit |

## Domain filter behavior

--allow is applied first (inclusion), then --block excludes. Suffix match:
wikipedia.org matches en.wikipedia.org but NOT notwikipedia.org.

## Research modes

| Mode | Max iterations | Behavior |
|------|---------------|----------|
| `speed` | 2 | Direct search, no planning step, no scrape |
| `balanced` | 6 | Plan -> search (embed-ranked) -> done |
| `quality` | 25 | Plan -> search -> LLM-pick best -> scrape -> extract -> repeat |

## Examples

```sh
sift
sift "what is the CFS scheduler in Linux"
sift --print "Rust async runtimes comparison"
sift --continue .ai/research/rust/async-runtimes.md "how does tokio compare to async-std?"
sift --print --continue .ai/research/rust/async-runtimes.md
sift --mode quality --allow wikipedia.org "explain mTLS"
sift --stream "HTTP/3 benefits"
sift --system "Answer in bullet points" "best Python testing libraries"
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | No synthesis produced |
| `2` | Bad invocation |
