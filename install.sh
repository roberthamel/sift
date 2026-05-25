#!/usr/bin/env bash
# Install sift as a thin wrapper on PATH that delegates to `uv run`
# from this checkout. Editable by construction — edits in src/ take
# effect on the next invocation.
#
# Usage:
#   ./install.sh                 # installs to $HOME/.local/bin/sift
#   ./install.sh ~/bin/sift      # custom target path
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$HOME/.local/bin/sift}"
MIN_UV="0.11.3"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv not found on PATH. Install it from https://astral.sh/uv" >&2
  exit 1
fi

uv_version="$(uv --version | awk '{print $2}')"
if [ "$(printf '%s\n%s\n' "$MIN_UV" "$uv_version" | sort -V | head -n1)" != "$MIN_UV" ]; then
  echo "error: uv $uv_version is older than required $MIN_UV. Run: uv self update" >&2
  exit 1
fi

echo "==> uv sync ($REPO_DIR)"
( cd "$REPO_DIR" && uv sync )

mkdir -p "$(dirname "$TARGET")"
echo "==> writing wrapper to $TARGET"
cat > "$TARGET" <<EOF
#!/usr/bin/env bash
exec uv run --project "$REPO_DIR" sift "\$@"
EOF
chmod +x "$TARGET"

case ":$PATH:" in
  *":$(dirname "$TARGET"):"*) ;;
  *) echo "note: $(dirname "$TARGET") is not on PATH — add it to your shell rc to invoke 'sift' directly." ;;
esac

echo "==> done. Try: $TARGET --help"
