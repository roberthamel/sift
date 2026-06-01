---
name: sift
description: |
  In-process research CLI: plan → SearXNG search → crawl4ai page-read → LLM synthesis.
  Auto-saves every answer to .ai/research/<scope>/<filename>.md with YAML frontmatter.

  Use this skill whenever you need to:
  - Research a question with current web sources: sift "question"
  - Run an interactive multi-turn research session: sift (no args)
  - Continue and enrich an existing research document: sift --continue <path>
  - Get a non-interactive answer to stdout: sift --print "question"
  - Stream NDJSON research events for programmatic use: sift --stream "question"
  - Configure depth with --mode speed|balanced|quality

  Make sure to use this skill whenever the user mentions web research, page fetching,
  content extraction, crawling, LLM synthesis of search results, or SearXNG — even if
  they don't explicitly name "sift".
  Sift is the successor to websearch-mcp and replaces it entirely.
compatibility: |
  Requires `uv` and Python >=3.12.
  The TUI renders in the terminal; --stream emits NDJSON to stdout; --print writes to stdout.
---

# sift — in-process web research CLI

## What it is

`sift` is a **single-command CLI** that runs a Vane-style multi-step research loop
entirely in-process — no server, no port, no Docker.

It uses [SearXNG](https://github.com/searxng/searxng) for searches and
[crawl4ai](https://github.com/unclecode/crawl4ai) for page reads, then synthesizes a
cited markdown answer via an OpenAI-compatible LLM.

Every answer is **automatically saved** to `.ai/research/<scope>/<filename>.md` in the
current directory. Follow-up turns **merge** new findings into the same file.

## Quick start

```sh
# Interactive REPL — prompts for question, loops until Ctrl-D
sift

# REPL seeded with first question
sift "give me an intro to Viper in a Golang CLI"

# Non-interactive: print answer to stdout, auto-save, exit
sift --print "what is HTTP/3"

# Continue an existing research document
sift --continue .ai/research/golang/viper-config-library.md "how does it handle env vars?"

# Stream NDJSON events for programmatic use
sift --stream "HTTP/3 benefits"

# Quality mode with domain filter
sift --mode quality --allow wikipedia.org "explain the CFS scheduler"
```

## Command interface

```
Usage: sift [OPTIONS] [QUERY]

  Research the web: plan → search → synthesize.
```

There are **no subcommands**. All options are research options.

| Flag | Default | Env var | Notes |
|------|---------|---------|-------|
| `QUERY` (positional) | (prompt if omitted) | — | Research question |
| `--mode {speed,balanced,quality}` | `balanced` | — | Research depth |
| `--print / -p` | off | — | Non-interactive: print answer to stdout and exit |
| `--continue / -c PATH` | (none) | — | Continue an existing research document |
| `--stream` | off | — | NDJSON events to stdout |
| `--llm-host URL` | — | `SIFT_LLM_HOST` | OpenAI-compatible base URL |
| `--llm-apikey KEY` | — | `SIFT_LLM_APIKEY` | Use `-` for local endpoints |
| `--llm-model NAME` | — | `SIFT_LLM_MODEL` | Model identifier |
| `--embed-base-url URL` | — | `SIFT_EMBED_BASE_URL` | Embedding endpoint |
| `--embed-api-key KEY` | — | `SIFT_EMBED_API_KEY` | — |
| `--embed-model NAME` | — | `SIFT_EMBED_MODEL` | Embedding model |
| `--system STR` | (none) | — | System instructions for the writer |
| `--history-file PATH` | (none) | — | JSON `[[role, text], ...]` |
| `--lang` | `all` | — | Search language |
| `--safesearch 0-2` | `0` | — | Safe search level |
| `--allow DOMAIN` | (none) | — | Repeatable domain allow filter |
| `--block DOMAIN` | (none) | — | Repeatable domain block filter |
| `--log-file PATH` | default | — | Rotating log file |
| `--verbose` | off | — | Raise log level to DEBUG |
| `--settings PATH` | bundled | — | Override settings.yml |

## Invocation forms

| Invocation | Behavior |
|------------|----------|
| `sift` | Prompt for question, run TUI, enter follow-up REPL |
| `sift "q"` | Seed first turn with query, enter follow-up REPL |
| `sift --print "q"` | One turn, print answer to stdout, exit |
| `sift --continue path` | Preload document, enter REPL |
| `sift --continue path "q"` | Preload document, first turn is query, enter REPL |
| `sift --print --continue path` | Refresh document, print answer, exit |
| `sift --stream "q"` | NDJSON events to stdout, exit |

## Auto-save

Every turn writes to `.ai/research/<scope>/<filename>.md`. The LLM picks the scope
folder and filename from the opening question. Files include YAML frontmatter:

```yaml
---
queries:
  - give me an intro to Viper in a Golang CLI
  - how does it handle environment variables?
created: 2025-06-01T14:22:10Z
updated: 2025-06-01T14:28:44Z
turns: 2
---
```

## Architecture

```
sift/
└── src/sift/
    ├── cli.py              # Entry point, _Session, mode dispatch
    └── research/
        ├── loop.py         # Iterative tool-calling researcher loop
        ├── writer.py       # Streaming synthesis writer (first-turn + merge modes)
        ├── persist.py      # Auto-save: pick_location, resolve_path, frontmatter
        ├── tui.py          # Rich Live TUI + follow-up REPL
        ├── prompts.py      # Researcher, writer, revision, picker, extractor prompts
        ├── actions.py      # plan / search / scrape_url / done tools
        ├── events.py       # EventBus
        └── embeddings.py   # Embedding client + cosine ranking
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | No synthesis produced |
| `2` | Bad invocation |

## Reference files

- **[references/commands.md](references/commands.md)** — Full option reference with examples
- **[references/schemas.md](references/schemas.md)** — NDJSON event schema and auto-save format
- **[references/research-loop.md](references/research-loop.md)** — Research loop architecture
- **[references/install.md](references/install.md)** — Installation and environment variables
