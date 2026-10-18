# Research Intelligence — full feature reference

A complete, detailed catalog of everything built in this project: all 16 core phases plus the
autonomous-agent work added afterward. This file is the exhaustive personal reference; **README.md**
is the shorter, public-facing version for GitHub visitors and recruiters.

For the session-by-session build log (what was tried, what broke, what real-model walkthroughs
found), see [PROGRESS.md](PROGRESS.md). For the phase plan and post-launch additions, see
[docs/ROADMAP.md](docs/ROADMAP.md).

---

## The one-line pitch

An AI research workspace where the retrieval pipeline is hand-built and inspectable end to end
(not a thin wrapper around an LLM API), *and* an autonomous agent that works on its own — it
searches arXiv on a schedule, scores what it finds, imports it, writes a literature review, and
tells you about it on Slack or Discord — without being asked each time.

---

## Part 1 — The 16 core phases (RAG research platform)

Each phase shipped backend → API → UI → responsive layout → tests, with a phase gate (tests
green, lint clean, manual walkthrough, docs updated) before the next one started.

### Phase 1 — Foundation
Project structure, config (Pydantic Settings, `.env`-driven), structured JSON logging, SQLAlchemy
2 async + Alembic migrations (PostgreSQL in prod, SQLite in dev — portable column types), JWT auth
with rotating httpOnly refresh cookies, a background job system (registry + runner + inline/Celery
dispatchers), per-IP and per-auth rate limiting, Prometheus metrics, Docker Compose, CI, a design
system (Tailwind v4 tokens, light/dark), the app shell (sidebar, command palette, mobile nav),
onboarding, and account settings.

### Phase 2 — Ingestion & parsing
Drag-and-drop multi-file upload with streamed size validation; dedupe (exact file-hash,
probable by DOI/arXiv id, possible by title similarity); versioning (re-upload keeps history);
parser providers behind one interface for PDF (PyMuPDF), DOCX, HTML, Markdown and plain text; OCR
fallback for scanned pages; a structure tree (sections, headings, figures, tables, equations,
references) with page/char offsets; metadata extraction with manual correction that survives
reprocessing; the Papers library (grid/list, live processing progress); the paper reader v1.

### Phase 3 — Chunking & embeddings
Five chunking strategies (fixed, recursive, sentence, section-aware — the default, never crosses
a section boundary — and semantic, splitting where embedding similarity between adjacent
sentences drops). Embedding providers (BGE/E5/sentence-transformers, OpenAI-compatible, a
hashing provider for fast deterministic tests) behind one interface. A model manager handles
device detection (CUDA/MPS/CPU), lazy loading and LRU + idle unloading so a laptop GPU never
holds every model at once. Content-hash-keyed embedding cache (identical text is never embedded
twice). Qdrant, embedded or server mode. Similar-papers v1.

### Phase 4 — Sparse & hybrid retrieval
A hand-written Okapi BM25 (Lucene IDF, configurable k1/b) over a per-user in-memory inverted
index that updates incrementally and stays correct across API/worker processes with no
invalidation messages; a PostgreSQL full-text-search alternative behind the same interface.
Dense retrieval via Qdrant ANN. Reciprocal Rank Fusion with per-retriever rank/score/contribution
kept in the trace. Metadata filters (year, author, type, chosen papers) resolved in SQL and
applied inside every retriever before its top-k cut. The Search page (simple/advanced) with a
"how these results were found" explanation panel.

### Phase 5 — Reranking
A cross-encoder reads each (query, passage) pair jointly and rescores the fused top-N; providers
behind one interface (local MiniLM/BGE cross-encoders, any Jina/Cohere-style `/rerank` API, a
lexical reranker for tests). Scores cached per (model, query, passage) so repeated/refined
searches skip the model. A failing reranker degrades to the fused order with a visible warning.

### Phase 6 — RAG chat + citations
LLM providers behind one interface: Ollama, any OpenAI-compatible API (OpenAI, vLLM, LM Studio,
OpenRouter, Groq, Mistral, NVIDIA...), and a deterministic extractive provider for tests. A
rule-based query processor (intent, entities, year filters parsed from phrases like "after 2023",
follow-up handling). Context selection: a relevance floor, near-duplicate removal, MMR for
diversity, token-budget packing — every keep/drop decision is recorded with its reason. SSE
streaming. A citation engine that validates every `[n]` against the passages actually sent, and a
claim-verification step (NLI entailment) that marks each sentence supported / unsupported / not
checked. General-purpose chat across paper and global scopes, with paper-grounded citations when
available and clearly labeled general answers for any topic; a split reader+assistant view and an
evidence panel.

### Phase 7 — Paper summaries
Structured summaries (problem → motivation → contribution → method → results → limitations →
future work) with a citation on every section, cached by a config key (model + prompt version) so
changing either regenerates automatically.

### Phase 8 — Comparison
A 2–5 paper side-by-side comparison table that says "Not reported" rather than inventing a value,
plus a methodology comparison and export.

### Phase 9 — Organization
Collections (grouping papers/notes/chats for a project, review, thesis or course), tags,
Markdown notes anchored to a passage/page/citation, bookmarks, and filtering the library by
collection or tag.

### Phase 10 — Knowledge graph & clustering
Entity extraction (datasets, models, methods, metrics, tasks) linked across the whole library;
a NetworkX graph with a Neo4j-ready interface; K-Means, HDBSCAN and agglomerative clustering
hand-written over NumPy, with LLM-assisted cluster naming (grounded — a name must appear in the
cluster's own content or it's rejected); a landscape visualization, a timeline, author analysis,
and dataset/model "who uses what" intelligence.

### Phase 11 — Literature review, gaps, disagreements & deep research
One `research_reports` table for four report kinds sharing a lifecycle (queued → running → ready,
one background job, numbered sources, a verification summary, editable sections). A literature
review: topic → retrieve → cluster into themes → chronology → disagreements → gaps → a fully
cited, claim-checked review. Disagreement detection: statement pairs sharing a named entity,
checked for contradiction both ways. Research-gap detection, split into "stated by the authors"
(their own limitations/future-work) and "system-generated" (untested combinations, conflicting
findings). A **bounded deep-research agent**: plans 2–4 sub-questions, searches the library with
one read-only tool, answers each from numbered passages (cited and checked), rewrites and retries
once if the evidence was thin, and writes a conclusion from what was actually cited — all under a
step count, token budget and wall-clock timeout, with every step recorded in a trace the UI shows.
Editing and export (Markdown, Word, PDF).

### Phase 12 — Research Project Builder
Added at the user's request, mid-build. Turns an idea into a guided, editable project: research
questions (suggested from the library, cited and checked) → background (a Phase 11 review) → gap
and hypothesis (from a gaps report) → a method plan (datasets, baselines, metrics actually used
by similar papers, each with its evidence) → an experiment and milestone plan → a cited paper
outline (introduction + related work built from checked statements, never an invented citation).
Suggestions are always kept visually separate from the user's own choices. Export to
Markdown/Word (plan) and LaTeX+BibTeX (outline).

**Project Builder extensions added afterward:**
- **arXiv import by id/link**, and **DOI lookup** via Crossref (arXiv DOIs import in full; other
  DOIs return metadata only, since there's no PDF to fetch without a guarded outbound fetcher).
- **Zip import**: a whole folder of papers in one upload, with hostile-archive defenses (entry
  names are labels only, never paths; size/ratio/entry-count caps; nested/password-protected
  archives skipped).
- **A step-by-step guide for every project step** (why, numbered actions, what you should end up
  with, common mistakes, and what's true of *your* project right now).
- **Starter code generation**: a real runnable Python project from the plan — tested metrics
  (accuracy, EM, F1, recall/precision/hit@k, MRR, nDCG), dataset loaders verified against real
  schemas (SQuAD, MS MARCO v2.1, HotpotQA, TriviaQA, NQ-Open), a runner that writes
  `results.csv`/`summary.md`, and **real, tested baseline components** (hand-written BM25, DPR,
  Contriever, a sentence-transformer, RRF, a cross-encoder reranker — public pretrained
  checkpoints, nothing retrained) that plan names map onto automatically. Anything unmapped stays
  a visible `TODO` stub — the generator never invents an implementation or a number.
- **"Draft the TODOs with your model"**: an LLM-drafted first attempt at the stub methods, from
  cited paper passages, explicitly labelled "LLM-drafted — unverified," syntax-validated before
  being shown.
- **An isolated code runner**: the generated project's toy-dataset smoke test runs inside a
  disposable, network-disabled container (read-only root, all capabilities dropped,
  no-new-privileges, 1 GiB memory/1 CPU/64 processes/40s wall clock) launched by a separate
  internal service — the API/worker process never executes a project's Python itself. Every run
  keeps its dataset, split, seed, source-file hash, runtime image digest and installed package
  versions for reproducibility.
- **Audit tooling**: a research-lineage map, a reproducibility preflight, a claim-evidence
  search with a reference attention-intervention experiment, and importing real experiment
  CSV/prediction-JSONL results to compare against a paper's reported numbers with cited evidence.

### Phase 13 — Evaluation
Hand-checked retrieval metrics (Recall@K, Precision@K, MRR, nDCG@K, paper recall@K) and answer
metrics (faithfulness and citation correctness from the same NLI checker used in chat —
deliberately not an LLM judge — context recall/precision, answer relevance, insufficient-evidence
rate). System metrics (latency p50/p95, throughput, tokens, cost). Runs snapshot the exact
retriever/reranker/LLM/verifier configuration they ran against, so A/B comparisons (2–4 runs) are
genuinely reproducible. A dataset editor (hand-written or model-drafted-then-verified questions).

### Phase 14 — Observability & performance
Every model call goes through a metering wrapper → `llm_usage` rows (tokens, latency,
time-to-first-token, cost priced at call time). A two-tier cache (process LRU + Redis, shared
across API and workers, survives restarts, fails open to local-only on a Redis outage). A
semantic answer cache that reuses an earlier checked answer for a near-identical question over
the *same* passages (guarded: cosine similarity alone can't tell a question from its reverse, so
names/numbers must match too). A usage & performance dashboard; a Prometheus/Grafana Compose
profile with a provisioned dashboard.

### Phase 15 — Testing & security
A cross-tenant test matrix driven directly by the OpenAPI schema: every route with a path id gets
another user's token thrown at it automatically — reads/deletes must 404, writes must never
succeed — and a new route fails the suite until it's registered, so nothing new can silently skip
the check. Startup recovery for jobs interrupted by a crash (resume, or fail cleanly after 3
interruptions so a bad file can't loop a process). A full personal data export, a security
activity log. Hardening: DOCX zip-bomb limits, a CSP for the SPA and the API, per-user concurrency
caps, `pip-audit`/`npm audit` in CI. A real end-to-end browser test (register → upload →
ask → cited, checked answer).

### Phase 16 — Polish & deployment
Demo mode with three synthetic sample papers (clearly labelled, no real publication claimed). A
full WCAG 2.1 A/AA accessibility audit (axe-core) across every page in light and dark theme.
Performance: lazy-loaded routes, a 117 kB gzipped main bundle. A full deployment guide (HTTPS,
backups, monitoring, scaling, upgrades).

### Post-16: your own model, or a free shared one
- **Settings → AI**: use the server's default model, bring your own API key (OpenAI, Gemini,
  Groq, OpenRouter, Mistral — encrypted at rest, write-only, never shown again), or point at a
  model on your own machine (Ollama, LM Studio, vLLM). Your choice follows every feature —
  chat, summaries, reviews, the deep-research agent, the project builder — with no per-feature
  wiring.
- **Run it entirely on your own computer**: a setup script checks prerequisites, installs
  everything, pulls a local model, and starts the app — no cloud account needed at all.
- **A free shared model for a public deployment** (the worked example: NVIDIA's Nemotron 3 Ultra,
  reached through the site's own key): strictly opt-in per user (nothing is sent anywhere until
  they choose it), per-user daily allowance, global pacing under the key's own rate limit, with
  retries that honor `Retry-After`.
- **Privacy, checked, not just claimed**: a dedicated test captures every log line through
  sign-up, upload, a note, a search, chat and a failed answer, and asserts none of it contains the
  question, the answer, a title, an email, or a filter string. The cross-tenant matrix also runs a
  second time *with an admin account* — `is_admin` grants no extra route access, by test.

---

## Part 2 — Research Watches: the autonomous agent

**The feature built specifically to be the standout, demoable differentiator**: "the system works
for you, not just when asked" — not another chat box.

### The core loop
A user saves a **watch**: a name, a topic/query, optionally linked to a Collection (where matches
land) and/or a Research Project (its question sharpens relevance scoring), an interval, a
relevance threshold, and whether to auto-import matches (**off by default** — a review queue, a
deliberate restraint choice). On a schedule, or on-demand ("Run now"):

1. **Search** — arXiv, since the watch's last search (a lookback window on the first run).
2. **Score** — every candidate's abstract, by embedding cosine similarity against the topic
   (averaged 50/50 with a linked project's research question, when there is one).
3. **Keep** — candidates at or above the threshold, capped per run.
4. **Record** — a digest entry per kept candidate, with a best-effort LLM "why relevant" blurb
   (never blocks the run; skipped entirely on a shared/free-tier model, so a background agent
   never spends someone's limited free allowance without them clicking anything).
5. **Import** (if `auto_import`) — through the exact same `DocumentService.import_arxiv` path a
   user-initiated import uses: the same size limits, dedup and per-user isolation apply.
6. **Notify** — an in-app notification (and, if configured, Slack/Discord), only when something
   was actually kept — a zero-result run stays quiet in the bell but is still visible in run
   history.

### No Celery beat
There's no separate scheduler service. The schedule is an in-process asyncio loop started from the
API's own `lifespan`, the same shape as the existing model-warmup background task — the one
design that works identically whether jobs run inline (dev, no separate worker process) or via
Celery (Docker): either way, the same process can write a `Job` row and ask the dispatcher to run
it. Claiming a due watch uses an **optimistic conditional `UPDATE ... WHERE next_run_at <= :now`**
(checking the row count) rather than `SELECT ... FOR UPDATE` — SQLite-compatible, and still
race-safe if the deployment ever scales to more than one backend process.

### Explainable trace
Every digest entry carries a `trace`: the search query used, the anchor text(s) it was scored
against, its rank among that run's candidates, and its score vs. the threshold. Not a new
computation — just data the run already had, not thrown away. Shown as a "Why this matched"
panel, the same collapsible pattern the deep-research agent's own trace already used elsewhere in
the app.

### Slack/Discord delivery
Settings → Notifications: one webhook per platform per account, reused by every watch. A saved
URL is validated against a **fixed host allowlist** (`hooks.slack.com`, `discord.com`,
`discordapp.com`) *before* it is ever stored or posted to — the same "fixed hosts only" posture
the arXiv/Crossref importers already use, which is what makes this safe from SSRF: it's not "POST
to any URL," it's "POST to one of two known webhook providers." Never echoed back in full
(`url_hint`: last 6 characters only — the same write-only pattern as a saved model API key).
Sending is best-effort and happens strictly after the run's own database commit, so a slow or
failing POST can never affect it.

### Auto-synthesis: a real literature review
A separate opt-in (`synthesize`, off by default, independent of `auto_import`): once a run keeps
enough candidates (3+, configurable), it **imports up to 8 of them even if `auto_import` is
off** — writing a review requires reading them, so this is its own explicit choice, not a
side-effect a cautious user would be surprised by. It then waits (bounded, 5 minutes) for them to
actually finish processing, and calls the **exact same `request_report` function** a
user-initiated literature review uses. The review itself runs as its own job and is read on the
existing Reports page — **nothing new was built for the review**; the only new code is "notice
enough things matched, import them, wait, and ask for the review the normal way." If no AI model
is configured, synthesis is skipped quietly — never a run failure.

A real correctness bug was found and fixed here during live verification: the run was initially
reporting `"succeeded"` while synthesis was still processing papers in the background, because
its status was written before the synthesis step that runs after it. Fixed by moving that write
to the true end of the job — re-verified live afterward that the run correctly stays `"running"`
for the entire wait.

### Public, no-login activity page
A third opt-in (`is_public`, off by default): `/public/watches/{id}` and its digest — the **first
deliberately unauthenticated routes in the whole app**. Gated by `is_public` plus the watch's own
unguessable UUID, the same trust model a signed asset URL already uses. Served through its own
minimal response schemas, never the authenticated ones, so a private field added to those later
can't leak here by accident: title, authors, abstract, arXiv id, published date, score, the LLM
blurb — never the owner's identity, their private library (`document_id`), `import_status`, or
anything about their other watches. A standalone frontend page with no app chrome at all; a "Copy
link" box on the watch's own page when it's public.

### What's reused vs. what's new
Reused, unchanged: the arXiv-import pipeline, `DocumentService`, the job registry/dispatcher, the
literature-review engine end to end, the deep-research trace UI pattern, the model-warmup
lifespan-task shape, the "fixed host allowlist" security pattern, the signed-asset-URL trust
model, the embedding provider and its cosine-similarity math already used for clustering. New:
four database tables (`agent_watches`, `agent_runs`, `agent_digest_entries`,
`notification_channels`), the scheduler loop, the relevance-scoring module, the run orchestrator,
the webhook sender, and the public route surface.

---

## Numbers (as of the last full run)

- **Backend**: 657 tests (648 by default + 9 opt-in real-model tests), ruff clean, mypy clean
  except two long-accepted pre-existing notes in embedding-provider code.
- **Frontend**: 170 unit tests + 7 browser end-to-end specs (accessibility, project guide, DOI,
  zip import, model choice, free shared model), typecheck and lint clean.
- **16/16 core phases complete**, plus the four Research Watches additions above, all with real
  (not just mocked) verification against the live dev server: real arXiv, real embeddings, a
  real NVIDIA-hosted model walkthrough, a real Slack-endpoint round trip.
- **Two real bugs found and fixed via live verification, not just unit tests**: a missing
  `run_after_commit` call that would have left auto-imported papers stuck `queued` forever outside
  a request context, and a run status reported `"succeeded"` before synthesis actually finished.
  Both have dedicated regression tests that fail if the fix is reverted.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Data | PostgreSQL (SQLite for local dev), Redis, Qdrant |
| Jobs | Celery + Redis (or in-process for local dev); an in-process asyncio scheduler for Research Watches |
| AI / ML | PyTorch, Transformers, sentence-transformers, NetworkX, PyMuPDF; hand-written BM25 and clustering (K-Means, agglomerative, HDBSCAN) in NumPy |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query, Zustand, Radix UI |
| Infra | Docker Compose, nginx, GitHub Actions, structured JSON logging, Prometheus metrics |

## Where things live (backend)

| Area | Path |
|---|---|
| Research Watches service layer | `backend/app/services/agent/` (`service.py` CRUD, `relevance.py` scoring, `runner.py` orchestration) |
| Watch/notification models | `backend/app/models/agent.py`, `models/notification.py`, `models/webhook.py` |
| Scheduler | `backend/app/workers/scheduler.py` |
| Watch job handler | `backend/app/workers/agent_watch.py` |
| Webhook sending + validation | `backend/app/services/webhooks.py` |
| Public (no-login) routes | `backend/app/api/routes/public.py` |
| Watches/notifications/webhooks API | `backend/app/api/routes/{watches,notifications,webhooks}.py` |
| RAG pipeline | `backend/app/services/retrieval/`, `services/rag/`, `services/reranking/` |
| Literature review / gaps / deep research | `backend/app/services/analysis/` |
| Research Project Builder | `backend/app/services/projects/` |

## Where things live (frontend)

| Area | Path |
|---|---|
| Watches pages | `frontend/src/pages/watches/{WatchesPage,WatchPage,PublicWatchPage}.tsx` |
| Watch create/edit dialog | `frontend/src/components/watches/WatchDialog.tsx` |
| Notification bell | `frontend/src/components/layout/NotificationBell.tsx` |
| Webhook settings | `frontend/src/pages/settings/NotificationChannels.tsx` |
| Data hooks | `frontend/src/hooks/{useWatches,useNotifications,useWebhooks}.ts` |

---

See [PROGRESS.md](PROGRESS.md) for exactly how and when each piece above was built, including the
real-model walkthroughs that found and fixed problems the automated tests alone didn't catch.
