---
name: sift
description: |
  In-process research CLI: plan → SearXNG search → crawl4ai page-read → LLM synthesis.
  Use this skill whenever you need to:
  - Research a question with current web sources (sift "question")
  - Run an interactive research session with follow-up (sift with no args)
  - Stream NDJSON research events for programmatic use (sift --stream "question")
  - Write the research answer to a markdown file (sift -o file.md "question")
  - Configure depth with --mode speed|balanced|quality
  
  Make sure to use this skill whenever the user mentions web research, page fetching,
  content extraction, crawling, LLM synthesis of search results, or SearXNG — even if
  they don't explicitly name "sift".
  Sift is the successor to websearch-mcp and replaces it entirely.
compatibility: |
  Requires `uv`, Python >=3.12, and the sift project checkout.
  The TUI renders in the terminal; --stream emits NDJSON to stdout; -o writes markdown.
---

# sift — in-process web research CLI

## What it is

`sift` is a **single-command CLI** that runs a [Vane-style](https://github.com/theckman/vane)
multi-step research loop entirely in-process — no server, no port, no Docker.

It uses [SearXNG](https://github.com/searxng/searxng) for searches and
[crawl4ai](https://github.com/unclecode/crawl4ai) for page reads, then synthesizes a
cited answer via an OpenAI-compatible LLM.

## Quick start

```sh
# Interactive research with follow-up REPL
sift

# One-shot research (live TUI output, then exit)
sift "what is HTTP/3"

# One-shot research + write answer to file
sift -o ANSWER.md "what is HTTP/3"

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

There are **no subcommands**. All options are research options:

| Flag | Default | Env var | Notes |
|------|---------|---------|-------|
| `QUERY` (positional) | (prompt if omitted) | — | Research question |
| `--mode {speed,balanced,quality}` | `balanced` | — | Research depth |
| `--stream` | off | — | NDJSON events to stdout |
| `-o / --output PATH` | (none) | — | Write synthesis to markdown file |
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
| `sift` | Prompt for question, run live TUI + follow-up REPL |
| `sift "q"` | Live TUI once, then exit |
| `sift -o file.md "q"` | Live TUI once, write markdown to file, exit |
| `sift -o file.md` | **Error**: question required when `-o` is given |
| `sift --stream "q"` | NDJSON events to stdout, then exit |

## Architecture

```mermaid
flowchart TB
    subgraph CLI["sift (single command)"]
        direction TB
        TUI["interactive TUI (default no-arg)"]
        ONESHOT["one-shot live render (sift &quot;q&quot;)"]
        STREAM["--stream NDJSON"]
    end

    subgraph Loop["Research loop (in-process)"]
        L1["runner.py — SearXNG search"]
        L2["fetcher.py — crawl4ai AsyncWebCrawler"]
        L3["research/loop.py — plan → search → embed → scrape"]
        L4["research/writer.py — LLM synthesis"]
    end

    CLI --> Loop
```

Key architectural principles:
- **No server, no port, no Redis** — everything runs in-process
- **Single command** — no subcommands; all options are research options
- **SearXNG** for search, **crawl4ai** for page reads
- **Lazy imports** — `openai`, `crawl4ai`, `searx` imported only when needed

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | No synthesis produced |
| `2` | Bad invocation (missing question with `-o`, unknown mode, LLM/embed not configured) |

## Reference files

- **[references/commands.md](references/commands.md)** — Full option reference with examples
- **[references/schemas.md](references/schemas.md)** — NDJSON event schema and `-o` output format
- **[references/research-loop.md](references/research-loop.md)** — Research loop architecture
- **[references/install.md](references/install.md)** — Installation and environment variables
