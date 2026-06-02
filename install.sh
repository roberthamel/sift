#!/usr/bin/env bash
# sift installer
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/roberthamel/sift/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/roberthamel/sift"
SXNG_REPO="https://github.com/searxng/searxng"
SIFT_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/sift"
TOOL_BIN="${HOME}/.local/bin"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ── uv ───────────────────────────────────────────────────────────────────────

if command -v uv >/dev/null 2>&1; then
  ok "uv found: $(uv --version)"
else
  info "uv not found — installing"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || \
    die "uv installed but not on PATH — open a new shell and re-run"
  ok "uv installed: $(uv --version)"
fi

# ── venv ─────────────────────────────────────────────────────────────────────

info "creating environment at $SIFT_HOME"
uv venv --allow-existing "$SIFT_HOME"
PYTHON="$SIFT_HOME/bin/python"

# ── searxng ──────────────────────────────────────────────────────────────────
# SearXNG is not on PyPI and its setup.py imports at build time, so we must
# pre-install its build deps and build with --no-build-isolation.

info "installing searxng build dependencies"
uv pip install --quiet --python "$PYTHON" \
  msgspec setuptools pyyaml babel \
  flask "flask-babel" jinja2 \
  "lxml==6.1.1" pygments "python-dateutil" \
  "httpx[http2]" "httpx-socks[asyncio]" \
  markdown-it-py isodate whitenoise certifi

info "installing searxng"
uv pip install --quiet --python "$PYTHON" \
  --no-build-isolation \
  "git+$SXNG_REPO"

# ── sift ─────────────────────────────────────────────────────────────────────

info "installing sift"
_OVERRIDE=$(mktemp)
printf 'lxml==6.1.1\n' > "$_OVERRIDE"
uv pip install --quiet --python "$PYTHON" \
  --override "$_OVERRIDE" \
  "git+$REPO"
rm -f "$_OVERRIDE"

# ── PATH / wrapper ───────────────────────────────────────────────────────────

mkdir -p "$TOOL_BIN"
ln -sf "$SIFT_HOME/bin/sift" "$TOOL_BIN/sift"
ok "linked $TOOL_BIN/sift → $SIFT_HOME/bin/sift"

case ":$PATH:" in
  *":$TOOL_BIN:"*) ;;
  *)
    printf '\n\033[1;33mnote:\033[0m add %s to your PATH:\n' "$TOOL_BIN"
    printf '  echo '\''export PATH="%s:$PATH"'\'' >> ~/.zshrc\n\n' "$TOOL_BIN"
    ;;
esac

info "done — try: sift --help"
