#!/usr/bin/env bash
# Starts backend (:8000) and frontend (:5173) for local development.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev,worker]"
fi
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python
"$PY" -m alembic upgrade head
"$PY" -m uvicorn app.main:app --reload --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT

cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run dev
