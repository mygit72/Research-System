#!/usr/bin/env bash
# Run Research Intelligence on your own computer, with a local model (macOS / Linux).
#
#   ./scripts/run-local.sh                     # default model (qwen2.5:3b)
#   ./scripts/run-local.sh llama3.2:3b         # another model
#   CHECK_ONLY=1 ./scripts/run-local.sh        # check, change nothing
#   NO_ML=1 ./scripts/run-local.sh             # skip PyTorch + embedding models (~1 GB)
#
# Checks Python 3.12+, Node 20+ and Ollama; the first time, writes backend/.env (your model,
# local models allowed, a random secret) and installs everything; pulls the model into Ollama;
# then starts the app at http://localhost:5173. Everything stays on this computer. Any model you
# pull later (ollama pull <name>) can be chosen in Settings -> AI.
set -euo pipefail
MODEL="${1:-qwen2.5:3b}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/backend/.env"
CODE_MODEL=""

version_of() { "$@" 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1; }
at_least() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }

problems=()
PYTHON="" PY_VERSION=""
for candidate in python3.13 python3.12 python3 python; do  # the first that really runs
  if command -v "$candidate" >/dev/null; then
    found="$(version_of "$candidate" --version || true)"
    if [ -n "$found" ]; then PYTHON="$(command -v "$candidate")" PY_VERSION="$found"; break; fi
  fi
done
if [ -z "$PY_VERSION" ] || ! at_least "$PY_VERSION" 3.12; then
  problems+=("Python 3.12 or newer: https://www.python.org/downloads/")
fi
NODE_VERSION="$(command -v node >/dev/null && version_of node --version || true)"
if [ -z "$NODE_VERSION" ] || ! at_least "$NODE_VERSION" 20.0; then
  problems+=("Node.js 20 or newer: https://nodejs.org/")
fi
OLLAMA="$(command -v ollama || true)"

echo
echo "Research Intelligence - local install"
echo "  Python : ${PY_VERSION:-missing}"
echo "  Node   : ${NODE_VERSION:-missing}"
echo "  Ollama : $([ -n "$OLLAMA" ] && echo found || echo 'missing (optional: you can use an API key in Settings -> AI instead)')"
echo "  Model  : $MODEL"
if [ ${#problems[@]} -gt 0 ]; then
  echo
  echo "Install these first, then run this script again:"
  printf '  - %s\n' "${problems[@]}"
  exit 1
fi
if [ -n "${CHECK_ONLY:-}" ]; then
  echo
  echo "Everything needed is installed. Run again without CHECK_ONLY to install and start."
  exit 0
fi

if [ ! -f "$ENV_FILE" ]; then
  SECRET="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > "$ENV_FILE" <<EOF
# Written by scripts/run-local.sh for a private install on this computer.
LLM_PROVIDER=ollama
LLM_MODEL=$MODEL
OLLAMA_BASE_URL=http://127.0.0.1:11434
ALLOW_LOCAL_MODELS=true
JWT_SECRET=$SECRET
EOF
  echo "Wrote $ENV_FILE"
else
  echo "Keeping your existing $ENV_FILE"
fi
CODE_MODEL="$(sed -n 's/^CODE_LLM_MODEL=//p' "$ENV_FILE" | head -1 | tr -d '\r' | xargs || true)"

cd "$ROOT/backend"
if [ ! -d .venv ]; then
  echo "Installing the backend (a few minutes the first time)..."
  "$PYTHON" -m venv .venv
  .venv/bin/pip install --upgrade pip
  if [ -z "${NO_ML:-}" ]; then
    .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
    .venv/bin/pip install -e ".[worker,ml]"
  else
    .venv/bin/pip install -e ".[worker]"
  fi
fi
cd "$ROOT/frontend"
[ -d node_modules ] || npm install

# Ask Ollama's API (2 s timeout) instead of `ollama list`, which can wait on a stopped server.
tags() { curl -s -m 2 http://127.0.0.1:11434/api/tags; }
if [ -n "$OLLAMA" ]; then
  if ! tags >/dev/null; then
    echo "Starting Ollama..."
    nohup "$OLLAMA" serve >/dev/null 2>&1 &
    for _ in $(seq 30); do tags >/dev/null && break; sleep 1; done
  fi
  if ! TAGS="$(tags)"; then
    echo "Ollama did not start. Start it yourself, then run this again."
  elif printf '%s' "$TAGS" | grep -qE "\"name\":\"$MODEL(:latest)?\""; then
    echo "Ollama has $MODEL."
  else
    echo "Downloading $MODEL into Ollama (once)..."
    "$OLLAMA" pull "$MODEL"
  fi
  if [ -n "$CODE_MODEL" ] && [ "$CODE_MODEL" != "$MODEL" ]; then
    TAGS="$(tags)"
    if ! printf '%s' "$TAGS" | grep -Fq "\"name\":\"$CODE_MODEL\""; then
      echo "Downloading coding model $CODE_MODEL into Ollama (once)..."
      "$OLLAMA" pull "$CODE_MODEL"
    else
      echo "Ollama has coding model $CODE_MODEL."
    fi
  fi
else
  echo "Ollama is not installed: answers need an API key (Settings -> AI) until you install it."
fi

echo
echo "Starting... open http://localhost:5173 and create an account (it stays on this computer)."
exec bash "$ROOT/scripts/dev.sh"
