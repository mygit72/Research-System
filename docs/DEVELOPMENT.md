# Development guide

## Prerequisites

- Python 3.12+
- Node.js 22+
- (Optional) Docker Desktop, for the full PostgreSQL/Redis/Qdrant/Celery stack

## Option A: run locally without Docker (fastest)

Uses SQLite, in-process background jobs and no Redis. Everything is configured by `.env`
(optional; defaults work).

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate           # Windows (Git Bash: source .venv/Scripts/activate)
# source .venv/bin/activate      # macOS / Linux
pip install -e ".[dev,worker]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173 (proxies /api to :8000)
```

Or run `scripts/dev.ps1` (Windows) / `scripts/dev.sh` (macOS/Linux) to start both.

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health, readiness: http://localhost:8000/ready
- Prometheus metrics: http://localhost:8000/metrics

## Option B: full stack with Docker

```bash
cp .env.example .env             # set JWT_SECRET for anything non-local
docker compose up --build
```

Open http://localhost:8080. Services: `postgres`, `redis`, `qdrant`, `backend` (runs
migrations on start), `worker` (Celery), `frontend` (nginx serving the SPA and proxying `/api`).

## Models and the search index

Uploads are chunked, embedded and written to Qdrant as the last stages of processing.
Locally, Qdrant runs embedded (files under `backend/data/files/qdrant`, i.e. `STORAGE_DIR/qdrant`); set `QDRANT_URL` to use
a server.

```bash
# Local embedding model (first use downloads BAAI/bge-small-en-v1.5, ~130 MB)
pip install torch --index-url https://download.pytorch.org/whl/cpu   # or .../whl/cu124 for CUDA
pip install -e ".[ml]"

# Rebuild the index after changing EMBEDDING_MODEL / CHUNKING_STRATEGY / CHUNK_SIZE
python -m app.cli reindex --all          # or --pending, --user someone@example.com
```

- Without `torch`/`sentence-transformers`, papers still process and stay readable; they are
  marked **Not searchable** with a retry button. `EMBEDDING_PROVIDER=hashing` is a
  dependency-free fallback used by the test suite (lexical only, not semantic).
- Embeddings are cached by `(model, sha256(text))`, so reindexing with an unchanged model only
  recomputes passages whose text changed.
- Vectors from different models never mix: each model/dimension gets its own collection.
- GPU in Docker: build with `--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124`
  and add to the `worker` service:
  `deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }] } } }`.

## Search internals

- `SPARSE_RETRIEVER=bm25` (default) keeps a per-user BM25 index in memory, built on first
  search and updated incrementally. `postgres` uses PostgreSQL full-text search instead (needs
  PostgreSQL; the GIN index is created by migration `9b1f4c2d7e10`).
- The PostgreSQL retriever test runs only against a real, migrated database:
  `TEST_POSTGRES_URL=postgresql+asyncpg://… pytest tests/test_postgres_fts.py` (CI does this).
- Reranking: the local cross-encoder downloads on first use (~90 MB for the default) and is
  warmed at startup. `RERANKER_PROVIDER=none` turns it off; `?rerank=0` turns it off for one
  search. The Search page shows fused results immediately and swaps in the reranked order.
- Add `?debug=1` to a Search page URL (or tick "Show how results were found" under Advanced)
  to see BM25, dense and fused rankings with scores, matched terms and per-stage timings.

## Research chat

- The default language model is Ollama `qwen2.5:3b`. Install Ollama from https://ollama.com,
  then `ollama pull qwen2.5:3b`. Settings → AI and the chat page say when it isn't reachable or
  the model isn't pulled; questions without matching evidence are still answered (with
  "insufficient evidence") because the model is never called for them.
- Other providers: `LLM_PROVIDER=openai` with `OPENAI_API_KEY` (+ `LLM_API_BASE` for vLLM, LM
  Studio, OpenRouter, NVIDIA or any other OpenAI-compatible API).
- `LLM_PROVIDER=fake` streams a deterministic extractive answer (used by the tests): handy for
  UI work without a model; it is not a real answer.
- Claim checking downloads `cross-encoder/nli-deberta-v3-xsmall` (~280 MB) once and is warmed at
  startup; `VERIFIER_PROVIDER=lexical` uses word overlap instead (no model).

## End-to-end test

`cd frontend && npm run e2e` starts an API with a fresh database and deterministic models
(`backend/scripts/e2e_server.py`, port 8010) and the production build (`vite preview`, with
the production Content-Security-Policy), then registers, uploads a paper, asks about it in
chat and checks the cited sources in Chrome. Any console error (including a CSP violation)
fails it. CI uses Playwright's Chromium.

## Usage, caches and metrics

- Every model call is recorded in `llm_usage` (Usage page, `GET /api/v1/usage`). Prices:
  `LLM_PRICES='{"model": [input, output]}'` (USD per million tokens) or
  `LLM_PRICE_INPUT_PER_MILLION` / `LLM_PRICE_OUTPUT_PER_MILLION`.
- Query embeddings and reranker scores are cached per process, and in Redis too when
  `REDIS_URL` is set. `CACHE_ENABLED=false` turns caching off for benchmarks.
- The semantic answer cache reuses an earlier, checked answer for a near-identical first
  question with the same passages: `ANSWER_CACHE_ENABLED`, `ANSWER_CACHE_MIN_SIMILARITY`
  (0.95), `ANSWER_CACHE_DAYS` (30). "Answer again" in chat bypasses it.
- Prometheus/Grafana: `docker compose --profile observability up`. Details in
  [OBSERVABILITY.md](OBSERVABILITY.md).
- In Docker, the backend reaches Ollama on the host through `host.docker.internal`.
- Real-model tests (embedder, reranker, NLI verifier) are opt-in: `RUN_MODEL_TESTS=1 pytest -q`.

## Tests and quality checks

```bash
cd backend
pytest -q                        # unit + API tests (SQLite, inline jobs)
ruff check app tests && ruff format --check app tests

cd frontend
npm test                         # vitest
npm run lint                     # oxlint
npm run typecheck
npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above, applies migrations up/down/up on a
real PostgreSQL, and builds the Docker images.

## Database migrations

```bash
cd backend
alembic revision --autogenerate -m "describe change"
# review the generated file in alembic/versions/, then:
alembic upgrade head
```

Use portable column types (`Uuid`, `JSONType` from `app.models.base`) so migrations work on
both SQLite and PostgreSQL.

## Adding a background job

```python
# app/workers/<feature>.py
from app.workers.registry import JobContext, JobFailedError, job_handler

@job_handler("document.process")
async def process_document(ctx: JobContext) -> dict:
    await ctx.report("parsing", 0.1)          # stage + progress shown in the UI
    ...
    raise JobFailedError("We couldn't read this PDF.", detail="xref error")  # user-safe
```

Import the module in `app/workers/handlers.py`, then enqueue from a service with
`JobService.enqueue(user_id, "document.process", subject_type="document", subject_id=...)`.
The job is dispatched only after the request's transaction commits.

## Conventions

- Routes stay thin: validation + DI + calling a service.
- Services raise `AppError` subclasses (`NotFoundError`, `ConflictError`, ...) with a
  user-facing `message` and optional `hint`; never return raw exceptions to clients.
- Frontend components call typed functions in `src/services/api.ts` via TanStack Query;
  no `fetch` in components, no business logic in components.
- Use design-system components (`src/components/ui`) and semantic color tokens
  (`bg-surface`, `text-muted`, `text-success` ...); no raw hex colors in components.
