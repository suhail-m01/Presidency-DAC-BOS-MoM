#!/usr/bin/env bash
# Start DAC Minutes Studio on one URL (http://localhost:8000).
#
#   ./run.sh              serve the application (Node.js not needed: dist ships built)
#   ./run.sh --rebuild    rebuild the interface first (needs Node.js)
#
# The Flask process serves both the API and the compiled interface, so there is no
# second server to manage. For frontend development use `cd frontend && npm run dev`
# (Vite on :3000 proxies /api to :8000).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "No Python environment yet. Creating one (first run only) ..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

# The archive ships the compiled interface (frontend/dist), so Node.js is only
# needed when it is missing or when you ask for a rebuild.
NEED_BUILD=0
[[ "${1:-}" == "--rebuild" ]] && NEED_BUILD=1
[[ -f "$ROOT/frontend/dist/index.html" ]] || NEED_BUILD=1

if [[ "$NEED_BUILD" == "1" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "The interface is not built and Node.js is not installed." >&2
    echo "Install Node.js 18+ (https://nodejs.org), then run: cd frontend && npm install && npm run build" >&2
    exit 1
  fi
  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "Installing frontend packages ..."
    ( cd frontend && { npm ci --no-audit --no-fund || npm install --no-audit --no-fund; } >/dev/null )
  fi
  echo "Building the interface ..."
  ( cd frontend && npm run build >/dev/null )
fi

echo
echo "  DAC Minutes Studio  ->  http://localhost:8000"
echo "  Sign-in codes appear in this terminal until a mail server is configured."
echo
exec ./.venv/bin/python app.py
