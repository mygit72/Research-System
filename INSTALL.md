# Installation SOP

A step-by-step procedure to install and run Research Intelligence yourself, without any
automated script. Use this if you want to see/control every step, the automated script
doesn't fit your setup, or something about it needs debugging. For the fast path, see
[Quick start in the README](README.md#quick-start) (`scripts/run-local.ps1` /
`scripts/run-local.sh`) or [docs/RUN_LOCALLY.md](docs/RUN_LOCALLY.md).

There are two ways to run it. Pick one:

- **A — Local, no Docker** (sections 1–7 below): SQLite, in-process jobs, no Redis. Fastest
  to set up, fine for one person's use.
- **B — Docker Compose** (section 8): PostgreSQL, Redis, Qdrant, Celery workers, the
  isolated code runner. Closer to how a shared/production instance runs.

---

## 0. Prerequisites

| Requirement | Why | Get it |
|---|---|---|
| Python 3.12 or newer | the backend (FastAPI) | https://www.python.org/downloads/ — on Windows, tick **Add python.exe to PATH** during install |
| Node.js 20 or newer | the web frontend (React/Vite) | https://nodejs.org/ |
| ~4 GB free disk space | PyTorch + search models (~1 GB) + a 3B language model (~2 GB) | — |
| ~8 GB RAM | running the models | — |
| (Optional) [Ollama](https://ollama.com) | a free local language model | only needed for path A if you want local chat answers instead of a hosted API key |
| (Optional) Docker Desktop | path B only | https://www.docker.com/products/docker-desktop/ |

A GPU is not required. CPU answers with the default 3B model take roughly 20–40 seconds.

Check your versions first:

```bash
python --version      # must print 3.12 or higher
node --version         # must print v20 or higher
```

---

## 1. Get the code

```bash
git clone <this repository's URL>
cd research-intelligence
```

(If you already have the folder, just `cd` into it.)

---

## 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and, at minimum, decide:

- **Language model**: the default (`LLM_PROVIDER=ollama`, `LLM_MODEL=qwen2.5:3b`) needs
  Ollama running locally (step 5). To use a hosted API instead, set
  `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...` (works with OpenAI, or any
  OpenAI-compatible endpoint via `LLM_API_BASE` — Groq, OpenRouter, Mistral, a local
  vLLM/LM Studio server, etc.). You can also skip this entirely and add a key later from
  the app itself (**Settings → AI**).
- **JWT_SECRET**: the placeholder value works for a local, single-user install. Generate
  your own before exposing the app to anyone else:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

Everything else has a working default for local use — see the comments in `.env.example`
for what each one does.

---

## 3. Install and start the backend

```bash
cd backend
python -m venv .venv

# Activate the virtual environment:
.venv\Scripts\activate                 # Windows (cmd/PowerShell)
source .venv/Scripts/activate           # Windows, Git Bash
source .venv/bin/activate               # macOS / Linux

# Base install (API only, no local embedding/reranking models):
pip install -e ".[worker]"

# Recommended: also install local search models (semantic search, reranking, claim
# checking). Install the matching PyTorch build for your machine first:
pip install torch --index-url https://download.pytorch.org/whl/cpu    # CPU
# pip install torch --index-url https://download.pytorch.org/whl/cu124  # NVIDIA GPU (CUDA 12.4)
pip install -e ".[worker,ml]"

# Apply the database schema (creates backend/data/app.db — SQLite by default):
alembic upgrade head

# Start the API:
uvicorn app.main:app --reload --port 8000
```

Leave this running. In a browser, http://localhost:8000/health should return `{"status":
"ok"}` and http://localhost:8000/docs shows the interactive API reference.

Without the `ml` extra, uploaded papers still parse and are readable, just marked **Not
searchable** (no embeddings) with a retry button once you install it later.

---

## 4. Install and start the frontend

In a **second terminal**, from the project root:

```bash
cd frontend
npm install
npm run dev
```

This serves the web app at **http://localhost:5173** and proxies `/api` requests to the
backend on port 8000. Leave this running too.

---

## 5. (If using the default local model) Install Ollama and pull the model

1. Install Ollama from https://ollama.com and make sure it's running (it starts
   automatically on most platforms; otherwise run `ollama serve`).
2. Pull the default model:
   ```bash
   ollama pull qwen2.5:3b
   ```
3. Confirm it answers: `ollama run qwen2.5:3b "say hi"`.

Skip this step entirely if you configured a hosted API key in step 2, or if you'll add a
key later from **Settings → AI** in the app.

---

## 6. First use

1. Open **http://localhost:5173**.
2. Create an account — it's stored only in your own database (`backend/data/app.db`),
   nothing leaves your machine.
3. Click **Try sample papers** (three synthetic papers, fastest way to see every feature)
   or upload your own PDFs.
4. Ask a question in chat, or use **Search** to try BM25 / dense / hybrid retrieval
   directly.

---

## 7. Stopping / restarting / updating

- **Stop**: Ctrl+C in each terminal (backend and frontend).
- **Restart**: re-run the `uvicorn ...` and `npm run dev` commands from steps 3–4. You do
  not need to repeat `pip install` / `npm install` / `alembic upgrade head` unless
  dependencies or migrations changed.
- **Update** (after pulling new code):
  ```bash
  cd backend && pip install -e ".[worker,ml]" && alembic upgrade head
  cd ../frontend && npm install
  ```
- **Back up your data**: everything you've uploaded and the account database live in
  `backend/data/` — back up that folder.
- **Change the model later**: pull any other Ollama model (`ollama pull mistral`) and
  pick it in **Settings → AI → A model on my computer → Test connection**, or switch to a
  hosted API key there.

---

## 8. Alternative: Docker Compose (path B)

Runs the full stack — PostgreSQL, Redis, Qdrant, Celery workers, the isolated code
runner, and an nginx-served frontend — in containers.

```bash
cp .env.example .env
# Set JWT_SECRET and PROJECT_RUNNER_TOKEN to real random values for anything beyond a
# private, local-only instance (see the comments in .env.example).
docker compose up --build
```

Open **http://localhost:8080**. The `backend` service applies database migrations on
startup. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for exposing this to other people
(HTTPS, backups, scaling) and [docs/SECURITY.md](docs/SECURITY.md) before doing so.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `pip install -e ".[worker,ml]"` fails on `torch` | Install torch first with the index URL shown in step 3 for your platform (CPU vs. CUDA), then retry. |
| Chat says the model is unreachable | Ollama isn't running, or the model wasn't pulled — see step 5. Or configure a hosted API key in **Settings → AI**. |
| Uploaded papers are stuck at "Not searchable" | The `ml` extra (torch + sentence-transformers) isn't installed, or the embedding model hasn't finished downloading on first use (~130 MB for the default). Check the backend terminal for errors. |
| Port 8000 or 5173 already in use | Something else is using it — stop that process, or run the backend with `--port <other>` and update `frontend/vite.config.ts`'s proxy target to match. |
| `alembic upgrade head` fails | Delete `backend/data/app.db` if you have no data to keep yet, and retry — or inspect the error, it usually names the exact migration/column at fault. |
| Changed `EMBEDDING_MODEL` / `CHUNKING_STRATEGY` / `CHUNK_SIZE` and search looks wrong | Existing papers were indexed with the old settings. Rebuild: `python -m app.cli reindex --all` (from `backend/`, venv active). |

For anything not covered here: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) (tests, migrations,
conventions), [docs/RUN_LOCALLY.md](docs/RUN_LOCALLY.md) (the automated script's details),
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (running it for other people), and
[docs/SECURITY.md](docs/SECURITY.md).
