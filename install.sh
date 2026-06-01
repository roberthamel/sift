#!/usr/bin/env bash
# sift installer
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/roberthamel/sift/main/install.sh | sh
set -euo pipefail

REPO="https://github.com/roberthamel/sift"

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

# ── sift ─────────────────────────────────────────────────────────────────────

info "installing sift"
uv tool install "git+$REPO"

# ── PATH hint ────────────────────────────────────────────────────────────────

TOOL_BIN="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
case ":$PATH:" in
  *":$TOOL_BIN:"*) ;;
  *)
    printf '\n\033[1;33mnote:\033[0m add %s to your PATH:\n' "$TOOL_BIN"
    printf '  echo '\''export PATH="%s:$PATH"'\'' >> ~/.zshrc\n\n' "$TOOL_BIN"
    ;;
esac

info "done — try: sift --help"
