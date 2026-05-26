# sift — installation and setup

## Prerequisites

- **Python >= 3.12**
- **uv >= 0.11.3** — install from https://astral.sh/uv
- **Git** — for cloning the repo and pinned sub-dependencies

## Installation

### From a local checkout (recommended)

```sh
cd sift
./install.sh                       # → ~/.local/bin/sift (default)
./install.sh ~/bin/sift             # or a custom target path
```

`install.sh` runs `uv sync` to build the project venv and drops a thin wrapper script on PATH that delegates to `uv run --project <repo>`. Edits to `src/sift/*.py` take effect on the next invocation — no reinstall step.

### Via uv tool (from a public repo — once published)

```sh
uv tool install git+https://<repo-url>
```

**Not recommended for this stack:** `uv tool install -e .` doesn't honor `[tool.uv].override-dependencies` or `[tool.uv.extra-build-dependencies]`, both of which are load-bearing here (see below).

### Without installing on PATH

```sh
cd sift
uv sync
uv run sift --help
```

## Project structure

```
sift/
├── src/sift/
│   ├── cli.py           # Typer entry point (all commands)
│   ├── runner.py        # In-process SearXNG search
│   ├── engines.py       # Engine resolution from settings.yml
│   ├── fetcher.py       # In-process crawl4ai page fetch
│   ├── serialize.py     # JSON serialization
│   ├── llm.py           # OpenAI-compatible LLM/VLM calls
│   ├── llm_config.py    # LLMConfig dataclass
│   ├── synthesize.py    # Search/fetch synthesis
│   ├── images.py        # Image source resolution
│   ├── inputs.py        # stdin URL resolution
│   ├── pretty.py        # Human-readable text renderer
│   ├── cache.py         # On-disk cache
│   ├── bootstrap.py     # Logging + settings init
│   ├── data/settings.yml  # Bundled SearXNG settings
│   └── research/        # Deep research loop
│       ├── loop.py, actions.py, prompts.py
│       ├── embeddings.py, embed_config.py
│       ├── utils.py, events.py
│       ├── writer.py, tui.py
├── tests/               # Pytest test suite
├── pyproject.toml       # Project config, deps, build
├── uv.lock              # Locked dependency versions
└── install.sh           # Wrapper installer
```

## Environment variables

### LLM configuration

| Variable | Required by | Notes |
|----------|-------------|-------|
| `SIFT_LLM_HOST` | synthesize, describe, research, --summary, --prompt | OpenAI-compatible base URL |
| `SIFT_LLM_APIKEY` | Same as above | Use `unused` or `-` for local endpoints |
| `SIFT_LLM_MODEL` | Same as above | Model identifier |
| `SIFT_VLM=1` | describe | Assert vision capability |
| `SIFT_LLM_TIMEOUT` | (optional) | Default 3600s (1 hour) |

### Embedding configuration

| Variable | Required by | Notes |
|----------|-------------|-------|
| `SIFT_EMBED_BASE_URL` | research | OpenAI-compatible embeddings endpoint |
| `SIFT_EMBED_API_KEY` | research | API key |
| `SIFT_EMBED_MODEL` | research | Embedding model name |
| `SIFT_EMBED_TIMEOUT` | (optional) | Default 600s |

### Other

| Variable | Used by | Notes |
|----------|---------|-------|
| `SEARXNG_SETTINGS_PATH` | bootstrap | Override settings.yml path |
| `XDG_STATE_HOME` | bootstrap | Default log file location |
| `XDG_CACHE_HOME` | cache | Default cache location |

## Why `uv tool install` doesn't work here

Two dependency issues prevent `uv tool install -e .` from working:

1. **lxml version conflict:** `crawl4ai` pins `lxml~=5.3` but `searxng` pins `lxml==6.1.1`. The project workspace overrides `lxml==6.1.1` via `[tool.uv].override-dependencies`. `uv tool install` skips this override.

2. **Missing build dependencies:** `searxng`'s build process imports `msgspec`, but `msgspec` isn't in `searxng`'s `build-system.requires`. The project adds missing build deps via `[tool.uv.extra-build-dependencies]`. `uv tool install` skips this section.

The wrapper-script approach (`install.sh`) sidesteps both by reusing the project's already-correct `uv sync` environment.

## Editable development

Since sift pins `searxng` and `crawl4ai` as editable sibling sources (in `[tool.uv.sources]`), you can edit either dependency and see changes immediately:

```sh
# Edit searxng code
vim ../searxng/searx/search/__init__.py

# Edit crawl4ai code
vim ../crawl4ai/crawl4ai/async_webcrawler.py

# Changes take effect on next `sift` invocation — no rebuild needed
```

## Testing

```sh
# All mocked tests (no live network, no browser)
uv run pytest

# Live crawl test (requires crawl4ai browser bundle)
SEARXNG_CLI_LIVE_CRAWL=1 uv run pytest -k live

# Live LLM test (requires configured SIFT_LLM_* env vars)
SIFT_LIVE_LLM=1 uv run pytest -k live_llm

# All tests including live
SEARXNG_CLI_LIVE_CRAWL=1 SIFT_LIVE_LLM=1 uv run pytest
```

## Logging

All logs go to a rotating file (1 MB × 3 backups) at:
- `$XDG_STATE_HOME/sift/sift.log` (defaults to `~/.local/state/sift/sift.log`)

Override with `--log-file` or `--verbose` (raises to DEBUG).

## Caching

Search responses are cached on-disk at `$XDG_CACHE_HOME/sift/` (defaults to `~/.cache/sift/`):
- SHA-256 keyed JSON files
- Default TTL: 3600 seconds (1 hour)
- `--cache-ttl 0` disables expiration
- `--no-cache` bypasses read and write
- `sift cache stats` / `sift cache clear` for management
