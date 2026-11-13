#!/usr/bin/env bash
# One command to bring this workspace back to a runnable state.
#
# The sandbox does not persist .venv/, node_modules/ or dist/ between sessions
# (they are excluded from snapshots), so after a restart they have to be rebuilt.
# This script is idempotent: run it any time, it only does the work that is missing.
#
#   ./bootstrap.sh          # repair Python + frontend, build the interface, seed the database
#   ./bootstrap.sh --run    # ...then serve the whole product on http://localhost:8000
#   ./bootstrap.sh --dev    # ...or run Vite on 3000 for frontend work (API on 8000)
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "== 1/4 Python environment =="
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  echo "   .venv already present"
else
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
  echo "   created .venv"
fi
./.venv/bin/python -c "import flask, reportlab, pypdf, docx, PIL, openpyxl, pptx" \
  && echo "   dependencies import cleanly"

echo "== 2/4 Frontend dependencies =="
# The archive ships the compiled interface. Node.js is only needed when that build is
# missing or when a rebuild is explicitly requested, so this stays runnable with Python
# alone — which is what the delivered archive promises.
if [[ -f "$ROOT/frontend/dist/index.html" && "${REBUILD_UI:-0}" != "1" ]]; then
  echo "   prebuilt interface present — skipping (set REBUILD_UI=1 to rebuild)"
elif [[ -d "$ROOT/frontend/node_modules" ]]; then
  echo "   node_modules already present"
else
  ( cd frontend && { npm ci --no-audit --no-fund || npm install --no-audit --no-fund; } >/dev/null )
  echo "   installed"
fi

echo "== 3/4 Frontend build =="
if [[ -f "$ROOT/frontend/dist/index.html" && "${REBUILD_UI:-0}" != "1" ]]; then
  echo "   using the shipped build"
else
  ( cd frontend && npm run build 2>&1 | tail -3 )
fi

echo "== 4/4 Database =="
./.venv/bin/python - <<'PY'
import auth_store
auth_store.init_db()
users = auth_store.list_users()
faculty = [u for u in users if u["role"] == "faculty"]
print(f"   {len(users)} accounts, {len(faculty)} faculty, "
      f"{len(auth_store.chairperson_candidates())} chairperson-eligible")
PY

if [[ "${1:-}" == "--dev" ]]; then
  echo "== starting development servers =="
  ./.venv/bin/python app.py > /tmp/dac-api.log 2>&1 &
  echo "   API -> http://localhost:8000  (log: /tmp/dac-api.log)"
  ( cd frontend && npm run dev > /tmp/dac-ui.log 2>&1 & )
  echo "   UI  -> http://localhost:3000  (log: /tmp/dac-ui.log)"
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
    sleep 1
  done
  echo "Done. Open http://localhost:3000 to sign in."
elif [[ "${1:-}" == "--run" ]]; then
  echo "== starting the application =="
  echo "   Open http://localhost:8000"
  echo "   (sign-in codes are printed in this terminal until a mail server is configured)"
  exec ./.venv/bin/python app.py
else
  echo "Done. Start it with: ./run.sh    (or ./bootstrap.sh --run)"
fi
