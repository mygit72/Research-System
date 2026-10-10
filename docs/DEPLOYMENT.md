# Deployment

How to run the platform for real users: one machine with Docker Compose, a reverse proxy for
HTTPS, backups, upgrades, and what to change when it outgrows one machine.

> **Verification status.** The compose stack is built in CI (`docker compose build`); the
> application inside it is the one tested by the backend, frontend and browser end-to-end
> suites. The full stack has not been run on the development machine (no Docker there), so
> treat the first deployment as a staging run and check the items under *After the first start*.

## What runs

| Service | Image | Role |
|---|---|---|
| `frontend` | nginx + the built SPA | serves the app with its security headers; proxies `/api` to the backend (same origin, so the `SameSite=Strict` refresh cookie works) |
| `backend` | Python 3.12 | applies migrations at start, then serves the API (`uvicorn`); embedding, reranking and claim-checking models load on first use |
| `worker` | same image | Celery worker: parsing, indexing, summaries, comparisons, reviews, evaluation runs |
| `postgres` | postgres:16 | all application data |
| `redis` | redis:7 | job broker, rate limits, shared cache |
| `qdrant` | qdrant | vector index |
| `prometheus`, `grafana` | *(profile `observability`)* | metrics and the provisioned dashboard |

The language model is **not** in the stack: point `LLM_PROVIDER` at Ollama on the host (the
default), an OpenAI-compatible server (vLLM, LM Studio) or a hosted API.

## Requirements

- CPU-only works: 4 cores and **8 GB RAM** run everything with `qwen2.5:3b` in Ollama (an
  answer takes 20–90 s; prompt reading dominates — see OBSERVABILITY.md). 16 GB is more
  comfortable with several users.
- An NVIDIA GPU speeds up the models: build with
  `--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124`, give the worker the GPU,
  and consider `RERANKER_MODEL=BAAI/bge-reranker-base` and a larger Ollama model.
- Disk: originals + rendered pages ≈ 3× the PDFs; models ≈ 1 GB (cached in the `model-cache`
  volume); Postgres and Qdrant grow with the number of passages.

## First deployment

```bash
git clone <repo> research-intelligence && cd research-intelligence
cp .env.example .env
```

Edit `.env` — at least:

```bash
ENVIRONMENT=production                       # Secure cookies; refuses the default JWT secret
JWT_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">
POSTGRES_PASSWORD=<random>
CORS_ORIGINS=https://research.example.org   # the public URL
ALLOW_REGISTRATION=true                     # false once your users have accounts
METRICS_TOKEN=<random>                      # if the API port is reachable (see below)
LLM_PROVIDER=ollama                         # on the host: `ollama pull qwen2.5:3b`
```

```bash
docker compose up -d --build
docker compose ps          # backend becomes "healthy" after migrations
```

The backend and worker containers get every setting in `.env` (Docker Compose 2.24 or newer);
the few that compose sets itself — database, Redis, Qdrant, `JOB_BACKEND` — stay as compose has them.

The app listens on `:8080` (frontend) and the API on `:8000`. Publish only the frontend: put
a TLS-terminating proxy in front of `:8080` and **remove the `8000:8000` and `6333:6333`
port mappings** (or firewall them) — `/metrics`, `/docs` and Qdrant shouldn't be public.

### HTTPS with Caddy (example)

```caddyfile
research.example.org {
    reverse_proxy localhost:8080 {
        flush_interval -1          # stream answers (server-sent events) without buffering
    }
}
```

nginx/Traefik work the same way; disable response buffering for `/api/v1/chat/*` and allow
uploads up to `MAX_UPLOAD_SIZE_MB` (the bundled nginx allows 100 MB) and, for the one route `POST /api/v1/documents/import/zip`, up to `MAX_ZIP_SIZE_MB` (the bundled nginx allows 200 MB there).

### After the first start

1. Open the site, register, and use **Try sample papers** on the empty library: three
   synthetic papers go through parsing, indexing and (if the model is reachable) summaries.
2. Settings → AI shows each model and whether the language model is reachable.
3. Ask a question in Research chat; the answer should cite the sample papers.
4. `curl -H "Authorization: Bearer $METRICS_TOKEN" localhost:8000/metrics | head`.
5. Set `ALLOW_REGISTRATION=false` if the instance is private, and restart `backend`.

## A free model for everyone (a public site)

A public site can give every visitor a free hosted model through the site's one key, next to
the two other choices each user has in **Settings → AI**: their own API key, or their own copy
of the app with a local model. The example is NVIDIA **Nemotron 3 Ultra**, free on OpenRouter.

1. Create an OpenRouter account and a key (openrouter.ai/keys), and look at its privacy settings:
   free models have their own data-policy switch there, and a model your settings exclude answers
   with an error. Free models are limited **for the whole account**: 20 requests a minute and
   **50 a day**, or **1,000 a day once the account has ever bought $10 of credits**
   (openrouter.ai/docs/api-reference/limits). Extra keys or accounts don't raise it. Without the
   $10, one user writing one literature review can use up the day's 50.
2. In `.env`:

   ```bash
   ENVIRONMENT=production
   LLM_PROVIDER=openai
   LLM_API_BASE=https://openrouter.ai/api/v1
   OPENAI_API_KEY=sk-or-v1-...
   LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
   LLM_EXTRA_BODY='{"reasoning": {"enabled": false}}'   # see step 3
   FREE_TIER=true
   FREE_TIER_LABEL=Nemotron 3 Ultra (free)
   FREE_TIER_HOST=NVIDIA, through OpenRouter
   FREE_TIER_REQUESTS_PER_MINUTE=15       # under the key's 20
   FREE_TIER_REQUESTS_PER_DAY=950         # under the key's 1,000 (45 without the $10)
   FREE_TIER_DAILY_REQUESTS_PER_USER=50
   DOWNLOAD_URL=https://…                 # where people get the code to run their own copy
   ```

3. **Check it before opening the site:** `python -m app.cli check-model` (in Docker:
   `docker compose exec backend python -m app.cli check-model`). It asks the model for a chat answer
   and a summary section the way the app does (two requests), prints each reply with the time to
   the first words and the token counts, and says whether each came back right.

   Nemotron 3 Ultra reasons before it answers, and that needs the `LLM_EXTRA_BODY` line above.
   Measured with the real model on 2026-10-11: with reasoning on, chat still worked (4–7 s before
   the first words, ~250 hidden tokens per answer), but summary sections hit their 450-token
   budget while still thinking and the thinking came back as the summary text.
   `{"reasoning": {"effort": "low", "exclude": true}}` changed nothing (535 reasoning tokens);
   `{"reasoning": {"enabled": false}}` gave clean, correctly formatted replies starting after
   1–3 s. For another model, start without the line and add it if the check reports a problem.

What `FREE_TIER=true` changes:

- **Nobody's text goes to the model until they choose it.** A new account has no model in
  effect; chat and summaries say "Choose how to run the AI features first" with a link to
  Settings. The Settings card says what the free model costs before the button: it is slower, it
  has a daily limit, and it runs at `FREE_TIER_HOST`, which receives the questions and the passages
  needed to answer them and may keep them. Users can turn it off again.
- **Pacing.** All users together make at most one call every `60 / FREE_TIER_REQUESTS_PER_MINUTE`
  seconds. A call that finds the slot taken waits its turn — this is why the free model is slow
  when the site is busy — for up to `FREE_TIER_MAX_WAIT_SECONDS`, then fails with "busy, try again".
  Shared across API and worker processes through Redis (the compose stack has it).
- **Allowance.** `FREE_TIER_DAILY_REQUESTS_PER_USER` model calls per user per UTC day, and
  `FREE_TIER_REQUESTS_PER_DAY` for the site. One chat answer is one call; a paper summary is
  several; a literature review is dozens. Calls refused for the allowance aren't sent or counted.
- **Retries.** A 429 or 5xx before any text arrived is retried twice, after the wait the service
  asked for.
- **No summaries on upload**, whatever `SUMMARY_AUTO` says: uploading a paper must not spend the
  allowance or send the paper anywhere. Users press **Generate** on the papers they want.
- People with their own key or their own copy are not paced or limited by any of this.

The site's key is used only for the address in `LLM_API_BASE`, is never sent to a user's own
address and never appears in a response. Nothing that identifies a user (id, email, IP) is sent
with a request: the host sees the site, not the person.

**The same model from NVIDIA's own API** (key from build.nvidia.com, starts with `nvapi-`):

```bash
LLM_PROVIDER=openai
LLM_API_BASE=https://integrate.api.nvidia.com/v1
OPENAI_API_KEY=nvapi-...
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b
LLM_EXTRA_BODY='{"chat_template_kwargs": {"enable_thinking": false}}'   # NVIDIA's way to turn thinking off
FREE_TIER_HOST=NVIDIA
FREE_TIER_REQUESTS_PER_MINUTE=30
FREE_TIER_REQUESTS_PER_DAY=0
```

Run for real on 2026-10-11: `check-model` passed, answers started after about 1.3 s, a paper
summary took 42 s over 5 calls. NVIDIA publishes no exact limit (about 40 requests a minute per
key is what people report, none per day), so the per-minute number above is a guess on the safe
side. **Read NVIDIA's terms before putting other people on it:** an NVIDIA reply on its developer
forum says free access is for research and testing and that production use needs an NVIDIA AI
Enterprise licence. Limits and terms of free services change: check them when you set this up.

## Demo instance

For a public demo: `ALLOW_REGISTRATION=true`, `LOCAL_ONLY=true` (no document text sent to
remote providers), a small `MAX_UPLOAD_SIZE_MB`, `CHAT_MAX_CONCURRENT_PER_USER=1`, and point
visitors to **Try sample papers**. The sample papers are original synthetic content written
for this project (labelled as such in every page header), so they can be shared freely.
Remember a CPU-only model serves one answer at a time; Ollama queues the rest.

## Monitoring

```bash
docker compose --profile observability up -d
```

Grafana on `:3000` (admin / `GRAFANA_PASSWORD`) with the *Research Intelligence* dashboard;
Prometheus on `:9090`. With `METRICS_TOKEN` set, give Prometheus the token
(`infra/observability/prometheus.yml` has the commented `authorization` block). Per-user
usage, cost and latency are also in the app under **Usage**. Logs are JSON
(`LOG_JSON=true`) with a request id on every line and in the `x-request-id` header.

Logs hold ids, routes, timings and error types — not what users read, ask or write
(`tests/test_private_work.py`). The bundled nginx logs the path without the query string for the same
reason: filters and searches travel in it. If you put another proxy in front, keep query strings
out of its access log too (Caddy logs no requests unless you add a `log` directive).

## Backups

Everything a user owns is in Postgres plus two volumes:

| What | How |
|---|---|
| Database | `docker compose exec postgres pg_dump -U research -Fc research > backup-$(date +%F).dump` |
| Uploaded files and rendered pages | the `file-storage` volume (`/app/data`) |
| Vector index | the `qdrant-data` volume — or skip it: it can be rebuilt with `python -m app.cli reindex --all` |
| Redis | not needed (jobs and caches) |

Restore: create an empty database, `pg_restore -d research backup.dump`, restore
`file-storage`, start the stack, and reindex if the vector volume wasn't restored. Test a
restore before you need one. Users can also download their own data (Settings → Privacy).

## Upgrades

```bash
git pull
docker compose up -d --build     # backend applies new migrations before serving
```

Migrations run automatically at backend start; take a database backup first. If a release
changes the embedding model or chunking, reindex (`docker compose exec backend python -m app.cli reindex --all`)
— until then, search warns that some papers were indexed with another model.

## Scaling beyond one machine

- **Workers** scale horizontally (`docker compose up -d --scale worker=3`); jobs are in Redis.
- **API replicas** need the shared pieces to be shared: Redis (rate limits, cache — already
  configured in compose), Qdrant server mode (`QDRANT_URL`, the default in compose), Postgres
  full-text search instead of the in-memory BM25 index (`SPARSE_RETRIEVER=postgres`).
  The per-user cap on concurrent answers is per process (see SECURITY.md).
- **Models**: run the language model on its own GPU host (vLLM with
  `LLM_PROVIDER=openai`, `LLM_API_BASE=…`); embeddings and reranking can move to API
  providers (`EMBEDDING_PROVIDER=openai`, `RERANKER_PROVIDER=api`) unless `LOCAL_ONLY`.

## Security checklist

- [ ] `ENVIRONMENT=production` and a random `JWT_SECRET` (the app refuses to start otherwise)
- [ ] HTTPS in front; only the frontend port published
- [ ] `METRICS_TOKEN` set, or `/metrics` unreachable from outside
- [ ] Registration closed if the instance is private
- [ ] `LOCAL_ONLY=true` if documents must never leave the machine
- [ ] `ALLOW_LOCAL_MODELS` unset or `false` on a public server (users' model URLs would otherwise
      reach the server's own network); `ALLOW_USER_API_KEYS=false` if users mustn't bring keys
- [ ] With `FREE_TIER=true`: `python -m app.cli check-model` answers; the per-minute and per-day
      limits are under the key's own; `FREE_TIER_HOST` names who receives users' text
- [ ] No proxy in front logs query strings; access to the server and its backups limited to who
      must have it (the app shows nobody other people's work, but the disk holds it)
- [ ] `MODEL_KEY_SECRET` set and kept with your secrets: it encrypts the API keys users save, and
      losing or changing it (or `JWT_SECRET` while it's unset) means users re-enter their keys
- [ ] Backups scheduled and a restore tested
- [ ] CI green (tests, browser end-to-end and accessibility checks, dependency audits)

See SECURITY.md for the controls behind these.
