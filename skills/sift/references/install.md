# sift installation and setup

## Install

```sh
curl -LsSf https://raw.githubusercontent.com/roberthamel/sift/main/install.sh | bash
```

Checks for uv, installs it if missing, then runs `uv tool install`.

### Manual

```sh
# Requires uv: https://astral.sh/uv
uv tool install git+https://github.com/roberthamel/sift
```

### Local checkout

```sh
cd sift
uv sync
uv run sift --help
```

## Environment variables

### LLM (required)

| Variable | Notes |
|----------|-------|
| `SIFT_LLM_HOST` | OpenAI-compatible base URL |
| `SIFT_LLM_APIKEY` | Use `-` for local endpoints |
| `SIFT_LLM_MODEL` | Model identifier |
| `SIFT_LLM_TIMEOUT` | Default 3600s |

### Embeddings (required)

| Variable | Notes |
|----------|-------|
| `SIFT_EMBED_BASE_URL` | OpenAI-compatible embeddings endpoint |
| `SIFT_EMBED_API_KEY` | API key |
| `SIFT_EMBED_MODEL` | Embedding model name |
| `SIFT_EMBED_TIMEOUT` | Default 600s |

### Other

| Variable | Notes |
|----------|-------|
| `SEARXNG_SETTINGS_PATH` | Override settings.yml path |
| `XDG_STATE_HOME` | Default log file location |
| `XDG_CACHE_HOME` | Default cache location |

## Testing

```sh
uv run pytest
```

## Logging

Rotating file at `$XDG_STATE_HOME/sift/sift.log` (default `~/.local/state/sift/sift.log`).
Override with `--log-file`. Use `--verbose` to raise to DEBUG.
