# Project Progress

> Updated at the end of every working session. Newest session first in the log.
> The full plan is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Current status

**All 16 phases: ✅ complete.** Possible next steps are listed at the end of the Session 9 / Phase 16 entry.

Overall: **16 / 16 phases done (100%), plus post-launch additions (see docs/ROADMAP.md)** ·
Backend tests: 657 (648 by default + 9 opt-in: real-model tests with `RUN_MODEL_TESTS=1`,
PostgreSQL in CI) · Frontend tests: 170 + 7 browser (end-to-end, accessibility, project guide,
DOI, zip import, model choice, free shared model)

| # | Phase | Status |
|---|---|---|
| 1 | Foundation: architecture, DB, Docker, auth, jobs, app shell | ✅ Done |
| 2 | Document ingestion, parsing, metadata, paper library UI | ✅ Done |
| 3 | Chunking, embeddings, Qdrant | ✅ Done |
| 4 | BM25, hybrid retrieval, RRF, search UI | ✅ Done |
| 5 | Reranking | ✅ Done |
| 6 | RAG chat, citations, verification, streaming | ✅ Done |
| 7 | Paper summaries | ✅ Done |
| 8 | Paper & methodology comparison | ✅ Done |
| 9 | Collections, tags, notes, bookmarks | ✅ Done |
| 10 | Knowledge graph, clustering, timeline, entities | ✅ Done |
| 11 | Literature review, gaps, contradictions, deep research | ✅ Done |
| 12 | Research Project Builder (added 2026-10-02) | ✅ Done |
| 13 | Evaluation framework & experiments | ✅ Done |
| 14 | Observability, caching, cost tracking | ✅ Done |
| 15 | Testing & security hardening | ✅ Done |
| 16 | UI polish, demo mode, deployment | ✅ Done |

## How to resume

```bash
# Windows
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1    # backend :8000 + frontend :5173
# Tests
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npm test
# Real-model test: RUN_MODEL_TESTS=1 pytest tests/test_embeddings_vectors_unit.py
# Rebuild the search index (after changing EMBEDDING_MODEL / chunking settings)
cd backend && .venv/Scripts/python -m app.cli reindex --all
```

---

## Session log

### Session 14: 2026-10-17 — four additions to Research Watches

User request, continuing Session 13's goal: "what more can we add?" → an explainable trace,
Slack/Discord delivery, auto-synthesis (a full literature review once enough papers match), and
an opt-in public (no-login) activity page.

#### Delivered
- **Explainable trace**: each digest entry now carries a `trace` (search query, the topic/project
  anchor text used, its rank among that run's candidates, score vs. threshold) — built from data
  the run already had, not a new computation. A "Why this matched" panel on the watch page shows
  it.
- **Slack/Discord delivery**: Settings → Notifications — one webhook per platform per account,
  reused by every watch. Saved URLs are validated against a fixed host allowlist
  (`hooks.slack.com`, `discord.com`/`discordapp.com`) before being stored or posted to — the same
  "fixed hosts only" posture as the arXiv/Crossref importers, so this is not a general
  outbound-fetch feature. Never echoed back in full (`url_hint`, last 6 characters). Sending is
  best-effort and happens after the run's own DB commit, so a slow/failing POST can't affect it.
- **Auto-synthesis** (`synthesize`, opt-in per watch, separate from `auto_import`): once a run
  keeps `agent_watch_synthesis_min_papers` (3) or more candidates, it imports up to
  `agent_watch_synthesis_max_papers` (8) of them — even if `auto_import` is off, since writing a
  review needs to read them — waits (bounded, 5 minutes) for them to finish processing, then calls
  the *same* `request_report` function `POST /literature-review` uses. The review runs as its own
  `report.generate` job and is read on the existing `/reviews/{id}` page; nothing new was built for
  that part. If no model is configured, synthesis is skipped quietly, not a run failure.
- **Public activity feed** (`is_public`, opt-in per watch, off by default): `/public/watches/...`
  — the first deliberately unauthenticated routes in this app (no `CurrentUser` on any of them).
  Gated by `is_public` plus the watch's own unguessable UUID (the same trust model as a signed
  asset URL). Served through its own minimal schemas, never the authenticated ones, so a private
  field added later can't leak here by accident: title, authors, abstract, arXiv id, published
  date, score, the LLM blurb — nothing about the owner, their library, or their other watches. A
  standalone frontend page (`/w/:id`, no `AppShell`) renders it; a "Copy link" box appears on the
  watch's own page when public.

#### A real correctness bug found and fixed while verifying this against the live dev server
Running a real `synthesize=true` watch showed the run reporting `"succeeded"` within ~16 seconds
— while 5 of its 8 imported papers were still `queued`/`processing` minutes later. `run.status`
and `run.finished_at` were being set to `SUCCEEDED` inside the main write-phase session, **before**
the synthesis step (wait-for-processing + review request) that runs after it — so a client
polling the run saw "done" while real background work was still in flight. Fixed by moving the
status/`finished_at` write to the true end of `execute_run`, after synthesis (success or skip).
Re-verified live: `imported_count` reached 8 within ~10 seconds, but `status` correctly stayed
`"running"` for the full ~55 seconds of real processing + the synthesis skip-check, only flipping
to `"succeeded"` at the true end.

#### Verified
- Backed by new tests: `test_webhooks_unit.py` (host allowlist, `url_hint`), `test_webhooks_api.py`
  (save/list/delete, `/test` against a mocked transport, rate limiting), `test_public_watches_api.py`
  (404 before `is_public`, safe fields only after, no cross-tenant-matrix applicability since there's
  no authenticated user to compare against), and new cases in `test_agent_watches_api.py` (trace
  fields present and sensible; `synthesize=true` with `auto_import=false` still imports and links a
  real `ResearchReport`; synthesis skips quietly with no model configured; webhook text posted on a
  kept run). `test_tenant_isolation.py` extended (`SKIP_PREFIXES` for `/public/`, `platform: "slack"`
  literal).
- **Real end-to-end walkthrough against the live dev server** (real arXiv, real BGE embeddings,
  this account's actual free-tier NVIDIA config): a `synthesize=true` run on "retrieval augmented
  generation" found 30 real papers, kept 10, imported 8 despite `auto_import=false`, and correctly
  waited for all 8 to really finish parsing/chunking/embedding (~2 minutes for 8 real PDFs) before
  giving up on synthesis with `"Choose how to run the AI features first."` — this account never
  chose a model, and the server's `FREE_TIER` is on, so nothing is sent to it until it does; a
  correct, intentional skip, not a bug. The success path itself (a real `ResearchReport` actually
  getting written) is covered by the automated test with a deterministic fake model instead, to
  avoid spending the account's real free-tier allowance just to prove the plumbing works.
  `/public/watches/{id}` real-checked 404 → 200 across the `is_public` toggle. The webhook `/test`
  endpoint made a real HTTPS request to `hooks.slack.com` with a deliberately invalid path and
  correctly reported `{"ok": false}` from Slack's own response — and a non-Slack/Discord host was
  refused with 422 before any request was made.
- Backend: 648 passed, 9 skipped (up from Session 13's 623 — 25 new tests). Full suite re-run
  clean both before and after the status-timing fix. Ruff clean; mypy adds no new categories
  beyond the one already accepted in `services/agent/relevance.py`.
- Frontend: 170 passed (9 new: `WatchDialog`'s two new toggles, `WatchPage`'s trace panel/review
  link/public-link box, `NotificationChannels`, `PublicWatchPage`). Typecheck and lint clean.

#### Not yet verified / known limitations
- The success path of synthesis (an actual `ResearchReport` produced) was only verified under the
  deterministic fake LLM used by tests, not against a real model — deliberately, to not spend the
  account's real free-tier quota. The user can verify this themselves by choosing a model in
  Settings → AI first.
- No real Slack/Discord channel was available to confirm an actual message arrives — only that
  the request reaches the real API and a failure is reported correctly.
- The UI was not visually exercised in a browser this session either (same tooling gap as Session
  13).

### Session 13: 2026-10-17 — Research Watches, an autonomous agent

User request: make the project stand out to recruiters beyond "just a RAG bot" — something that
shows the system working on its own, not only when asked.

#### Delivered
- **"Research Watches"**: a user saves a watch (name, topic/query, optional link to a Collection
  and/or a Research Project, interval, relevance threshold, `auto_import`). On a schedule, or
  "Run now", the system searches arXiv for new papers since the watch's last search (a lookback
  window on the first run), scores each candidate's abstract by embedding cosine similarity
  against the topic (averaged 50/50 with a linked project's research question, if any), keeps
  those above the threshold (capped per run), and records a digest entry for each — importing it
  into the library and attaching it to the collection when `auto_import` is on (**default off**: a
  review queue, a deliberate restraint choice), otherwise leaving a one-click "Add to library" for
  the user. A best-effort LLM "why relevant" one-line blurb is attempted per candidate (never
  blocks the run; skipped entirely on the free tier, same reasoning as auto-summarization). A
  notification is written only when at least one candidate was kept — a zero-result run stays
  quiet in the bell but is still visible in run history.
- **No Celery beat**: the schedule is an in-process asyncio loop (`workers/scheduler.py`) started
  from `main.py`'s `lifespan`, the same shape as the existing model-warmup task — works
  identically with inline jobs (dev/SQLite) and Celery (Docker). Claiming a due watch uses an
  optimistic conditional `UPDATE ... WHERE next_run_at <= :now` (SQLite-safe, no `SELECT FOR
  UPDATE`).
- **`services/arxiv.py` gained `search()`** (by query, not just fetch-by-id) and
  `parse_atom_entries()` (every `<entry>` in a multi-result feed); `parse_atom`'s per-entry
  parsing was refactored into a shared `_parse_entry()` so `fetch()` is unchanged.
- New tables: `agent_watches`, `agent_runs`, `agent_digest_entries`, `notifications` (migration
  `737abcbc799c`). New routes: `POST/GET/PATCH/DELETE /watches`, `.../run`, `.../runs`,
  `.../digest`, `.../digest/{id}/import`; `GET /notifications`, `.../unread-count`, `.../{id}/read`,
  `.../read-all`.
- Frontend: a "Watches" nav entry, `WatchesPage`/`WatchPage`, a create/edit dialog, and a
  `NotificationBell` (unread-count badge, mark read / mark all read) mounted in `AppShell`.
- **A real correctness bug found and fixed while writing this**: a job enqueued by code that runs
  *outside* a request (the scheduler's tick, and the watch-run job itself, when it auto-imports a
  match) must call `run_after_commit(session)` itself — the normal `DbSession` FastAPI dependency
  does that after every request, but nothing does it for code that isn't handling a request.
  Missed, an auto-imported paper's `document.process` job would be registered but never
  dispatched, and the document would stay `queued` forever. A dedicated regression test disables
  the call and confirms the test fails, then restores it and confirms it passes.
- **A second real bug found via a scheduler test**: the scheduler's claim `UPDATE` used
  SQLAlchemy's default `synchronize_session="evaluate"`, which compares the update's `WHERE`
  clause against already-loaded in-memory objects — on SQLite those come back with naive
  datetimes while `utcnow()` is timezone-aware, so the comparison raised `TypeError: can't compare
  offset-naive and offset-aware datetimes`. Fixed with `execution_options(synchronize_session=False)`
  (nothing in the scheduler relies on in-memory sync here).

#### Verified
- Backend: 623 passed, 9 skipped (up from 599 passed before this session) — 24 new tests
  (`test_arxiv_search.py`, `test_agent_relevance_unit.py`, `test_agent_scheduler_unit.py`,
  `test_agent_watches_api.py`, `test_notifications_api.py`) plus the required
  `test_tenant_isolation.py` fixture extension (`watch_id`, `entry_id`, `notification_id`). Ruff
  clean on every changed file; mypy adds 2 new "Returning Any from ndarray" notes in
  `services/agent/relevance.py` — the same pre-existing category already present, unaddressed, in
  4 other embedding-provider functions.
- Frontend: 161 passed (up from 149) — `WatchDialog`, `WatchesPage`, `WatchPage`,
  `NotificationBell` tests. Typecheck and lint clean.
- **Real end-to-end walkthrough** against the live dev server (real arXiv API, real BGE-small
  embeddings, local Ollama): created a watch for "retrieval augmented generation", ran it —
  30 candidates found on live arXiv, 10 kept above a 0.2 threshold (real cosine scores clustered
  0.65–0.72), a notification written, run completed in ~3.5 s. Manually added the top-scored
  digest entry to the library: the real PDF, title and all 6 authors came back correctly from
  arXiv, and the paper reached `ready` after its normal `document.process` run. The LLM blurb
  came back empty because the dev machine's Ollama wasn't running at the time — confirmed
  graceful, not a crash. No browser-automation tool was available in this session to click
  through the UI visually; the API-level walkthrough above is what verifies the real pipeline
  end to end.

#### Not yet verified / known limitations
- The scheduler has only been load-tested at the unit level with a stubbed run, not under
  multiple concurrent backend processes (the optimistic `UPDATE` is designed for that case but
  untested there).
- The "why relevant" blurb's quality (beyond "doesn't crash the run") hasn't been evaluated.
- The UI has not been visually exercised in a real browser this session.

#### Open
- arXiv's `all:<query>` search is unquoted (keyword-style): a multi-word topic is effectively
  ANDed, which can starve a broad topic of results; quoting would be exact-phrase, which can be
  too strict. Shipped as unquoted; worth tuning once real watches have run for a while.

### Session 12: 2026-10-10 — a free shared model for a public site; who can see a user's work

User request: (1) a user's session stays private — on their PC and the server, published nowhere,
seen by nobody else, "not even me"; (2) a free-tier key on our site (NVIDIA Nemotron Ultra, free);
(3) each user chooses: our free model (slow), their own API key, or download and run it themselves.

- **The free shared model** (`FREE_TIER=true`, `services/llm/free_tier.py`): the server's model
  (`LLM_PROVIDER=openai`, `LLM_API_BASE=https://openrouter.ai/api/v1`,
  `LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free` — id checked against OpenRouter's public
  model list; NVIDIA's own API lists it too) reached through the site's one key.
  - **Opt-in**: it runs at a third party, so with `FREE_TIER` on no model is in effect for an
    account until its owner chooses (preset `free` in `user_model_choices`, no migration; audited;
    undoable). Chat / summaries say "Choose how to run the AI features first" + link to Settings.
  - **Allowance**: per user per UTC day (`FREE_TIER_DAILY_REQUESTS_PER_USER`, 50) and for the site
    (`FREE_TIER_REQUESTS_PER_DAY`), counted from `llm_usage` rows with provider `free`; shown in
    Settings ("42 of 50 requests left today"); refused calls are neither sent nor recorded.
  - **Pacing** (the "slow" part): one call every `60 / FREE_TIER_REQUESTS_PER_MINUTE` s for all
    users together, waiting up to `FREE_TIER_MAX_WAIT_SECONDS`; Redis-shared when configured.
  - **Retries**: 429 / 5xx before any text → twice, honouring Retry-After. `LLMError` now carries
    `status`, `retry_after`, `sent`; the OpenAI-compatible provider reads errors reported inside a
    200 stream (OpenRouter does that) and takes `LLM_EXTRA_BODY` (reasoning settings).
  - **No summaries on upload** on the free model (allowance, and the paper would leave the server).
  - `python -m app.cli check-model`: one real question to the server's model, prints reply, time
    to first words, tokens; explains an empty / cut-off reply (reasoning model vs. answer budget).
- **Settings → AI**: three cards — *Free shared model* (what it costs: slower, daily limit, where
  it runs and that the host may keep what it gets; then "Use the free model"), *My own API key*,
  *Run it on my computer* (on a public server: download link from `DOWNLOAD_URL` + the run-local
  steps; on your own copy: the local-model form as before). Help page updated.
- **Privacy** — what was checked and what was changed:
  - No account can reach another's data, **administrators included**: the cross-tenant matrix now
    runs a second time with `is_admin=True` (67 routes; `is_admin` grants no route).
  - **Logs carry no content**: `tests/test_private_work.py` captures every log line at every level
    through sign-up, upload, a note, a library filter, chat, a summary and a failed answer, and
    looks for the question, answer, note, title, paper text, author, file name, filter, email, name.
  - **Found and fixed**: the bundled nginx used the default access log, which records query
    strings — library filters, graph / entity / author searches (`?q=`) and signed file links were
    being written to the server's log. Now `log_format no_query` (`$uri`), with a test.
  - Settings → Privacy → **Who can see your work** and SECURITY.md say it plainly, including the
    limit: whoever runs a hosted server can technically read what is stored on it; only your own
    copy with a local model is private from everyone. Requests to a model host carry no user id,
    email or IP (tested).
- **Deployment**: docker-compose passed only a fixed list of variables to the containers, so
  `LLM_API_BASE`, `METRICS_TOKEN`, `LOCAL_ONLY`, `ALLOW_*`, `MODEL_KEY_SECRET` (and the new
  `FREE_TIER_*`) set in `.env` never reached the app. `env_file: .env` added to backend and worker
  (explicit values still win). DEPLOYMENT.md: "A free model for everyone", checklist items.

#### Verified
- Backend **551 passed, 9 skipped** (16 free-tier tests, 2 private-work tests, the admin run of
  the tenant matrix). Mutation-checked, 13 of 13 caught: the opt-in gate, the allowance, metering of
  refused calls, auto-summary, retries, the site limit, limits applied to own-model users,
  `LLM_EXTRA_BODY` replacing the model, status "ready" with nothing chosen; a question / a query
  string / an email planted in the logs; nginx back on its default log. ruff clean; no new mypy errors.
- Frontend 136 unit tests (2 new), typecheck, lint. New browser test
  `e2e/free/free-model.spec.ts` (own config `playwright.free.config.ts`: an API started with
  `FREE_TIER` against a stand-in host): nothing sent before the choice → Settings card → choose →
  answer through the site's key, no user details in the request → third question refused at a
  2-a-day allowance and not sent → turn off; axe light + dark, 390 px, no console errors.
- `check-model` run with Ollama stopped (says how to fix it), then for real (below).

#### Real Nemotron 3 Ultra (2026-10-11, the user's OpenRouter key in a local `.env`)
- First real pass through the app (throwaway database; register → upload → choose the free model
  → two questions → one summary): **chat worked** (correct, cited, "supported"; 5–8 s, of which
  4–7 s before the first words; ~250–300 output tokens for a one-sentence answer).
  **Summaries did not**: 5 of 7 calls stopped at the 450-token budget, the summary took 115 s,
  and the model's thinking ("The user wants me to summarize… Now, PROBLEM: What problem…") came
  back as the summary text. A direct probe showed why: this endpoint streams the reasoning in the
  answer channel as well when the reply is cut off mid-thought.
- Three settings compared on the same summary request: default → 547 reasoning tokens, cut off;
  `{"reasoning": {"effort": "low", "exclude": true}}` (what I had suggested) → 535 reasoning
  tokens, still cut off, thinking still in the answer; **`{"reasoning": {"enabled": false}}` →
  182 tokens, first words after 2.9 s, all fields in the right format.** That is now the
  documented `LLM_EXTRA_BODY` for this model (.env.example, DEPLOYMENT.md, config comment).
- Second pass with reasoning off: answers in 1.6 s and 10.5 s (27 and 40 output tokens), the
  summary in 20 s over 5 calls, sections "Well supported"; allowance counted 7 of 20.
- **`check-model` now asks for a summary section too** (the app's own summary prompt and budget)
  and says what is wrong — empty, cut off, text before the first field, fields missing: the
  one-question version had passed while summaries were broken. 5 tests, one of them the real
  thinking-out-loud reply.
- **The developer's `.env` no longer reaches the tests**: with it in place the suite failed
  (FREE_TIER on for every test) and tests would have held the real key. `NO_ENV_FILE=1`, set by
  `tests/conftest.py` and the end-to-end server, makes settings ignore `.env` files.
- With the `.env` in place: backend **556 passed, 9 skipped**; all 7 browser tests pass.
- 22 requests were made to OpenRouter in all (of the account's 50 a day).
- **Then NVIDIA's own API** (the user's `nvapi-` key; `LLM_API_BASE=https://integrate.api.nvidia.com/v1`,
  `LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b`): thinking is turned off there with
  `LLM_EXTRA_BODY='{"chat_template_kwargs": {"enable_thinking": false}}'` (NVIDIA's documented
  setting; worked first time on Ultra). `check-model` passed; the same pass through the app: both
  answers in ~1.5 s, the summary in 42 s over 5 calls (two calls streamed slowly: 12 s and 18 s),
  7 calls counted. The local `.env` now points at NVIDIA, with the OpenRouter block kept
  commented out. No daily limit is published; the terms may restrict the free key to testing
  (an NVIDIA forum reply says production needs an AI Enterprise licence) — the user's to check.

#### Providers trimmed, and the repository made ready to publish (2026-10-11, at the user's request)
- The language-model providers are now **Ollama and OpenAI-compatible APIs only** (OpenAI,
  Gemini, Groq, OpenRouter, Mistral, NVIDIA, any custom server). The one SDK-based provider was
  removed from the app, the downloadable starter code, the settings (`LLM_EFFORT`, its key, the
  `llm` install extra), tests and docs. A choice saved for a removed provider falls back to the
  server's model. The starter's generator needs no provider SDK any more.
- Found on the way: with `LLM_PROVIDER=openai`, `LOCAL_ONLY=true` and no `LLM_MODEL`, the error
  talked about the missing model before saying remote models are off; `LOCAL_ONLY` is now said
  first.
- After the removal: backend **553 passed, 9 skipped**; frontend 136; all 7 browser tests;
  `check-model` against the real Nemotron on NVIDIA still passes.
- The original brief file was deleted. Commit history was rewritten once: author email changed
  on all commits, co-author trailers removed (content, dates and titles unchanged).

#### Not verified
- Every other hosted provider (OpenAI, Gemini, Groq, Mistral): no keys. On Nemotron: reviews, comparisons, deep research and the project builder were not run
  for real (a review alone is dozens of requests); answer quality with reasoning off was seen on
  one sample paper only.
- The Docker changes (compose `env_file`, the nginx log format): no Docker on this machine.

#### Open
- OpenRouter's free limit is for the whole account: 50 requests a day, 1,000 after a one-time $10
  of credits. A site for more than a couple of people needs the $10 or NVIDIA's own API.
- "Not even the site's owner" holds for the app (no screen, no logs) but not for the server's
  disk. Closing that needs content encrypted with a key only the user holds — a redesign of
  search and background jobs; not started.

### Session 11 (continued): your own model — bring your API key, or run it with a local model

User request: each user can either add their own API key (kept private) or download the system
and run it locally with any local model.

- **Settings → AI → "Language model for your work"**: this server's model, **my own API key**
  (presets: OpenAI, Google Gemini, Groq, OpenRouter, Mistral — base URLs checked
  against each provider's docs; Gemini/Groq/OpenRouter `:free`/Mistral have free tiers, with a
  note that free tiers may train on prompts), or **a model on my computer** (Ollama, or any
  OpenAI-compatible server: LM Studio, vLLM, llama.cpp). "Test connection" lists the models a
  key / local server offers (no tokens spent; never follows redirects); pick one, save.
- **Keys**: table `user_model_choices` (migration 5665d04f1f51), Fernet-encrypted under
  `MODEL_KEY_SECRET` or a key derived from `JWT_SECRET` (HKDF). Write-only: responses show `…last4`;
  audit logs preset+model only; the data export omits key and ciphertext; account deletion
  cascades. A rotated secret → "enter your key again", never a crash. `cryptography` added.
- **How it takes effect**: the user's choice is put in a context variable per request
  (`get_current_user`) and per job (`workers/runner.py`); `get_llm`, `resolve_model`,
  `current_model`, `provider_name`, `llm_status` read it. So chat, summaries, comparisons,
  reviews, deep research, the project builder, readiness checks, cache keys and usage rows all
  follow the user's model with no per-feature changes (cache keys unchanged for server-default
  users). The downloaded **starter code uses the same model**, key read from an env var named
  per provider (`GROQ_API_KEY`, …; new `api_key_env` in generation.py), never written to files.
- **Safety**: hosted presets only at fixed addresses; user-given URLs (Ollama/custom) only when
  `ALLOW_LOCAL_MODELS` (unset = on except in production) — no SSRF on a public server; the
  server's own keys are never sent to a user's address; `LOCAL_ONLY` refuses saved keys;
  `ALLOW_USER_API_KEYS` can switch keys off; connection test rate-limited like sign-in.
- **Run it on your computer**: `scripts/run-local.ps1` / `run-local.sh` — checks Python 3.12+,
  Node 20+, Ollama; first run writes `backend/.env` (model, local models on, random secret, no BOM)
  and installs (CPU PyTorch + ML extras unless `-NoML`); starts Ollama if needed (API check on
  127.0.0.1 with timeouts), pulls the model if missing, starts the app. `docs/RUN_LOCALLY.md`,
  Help page cards, README, `.env.example`, DEPLOYMENT checklist, SECURITY.md section.
- Fixes found on the way: OpenAI-compatible provider sent `Authorization: Bearer ` with no key
  (keyless local servers would fail); SQLite pool without pre-ping handed a connection broken by a
  cancelled request to the next request (HTTP 500 "no active connection") — `pool_pre_ping` on.
  Two axe checks were flaky (measured colours mid-fade) — they now emulate reduced motion.

#### Verified
- Backend 22 new tests (`tests/test_user_models.py`): encryption + rotation, never shown /
  logged / exported, keep-key-on-model-change, bad input reasons, public-server refusal of local
  models and URL probes, LOCAL_ONLY, per-user isolation, preset addresses and auth headers (mock
  transport), redirect not followed, local model listing, chat on the user's local model, server
  key never sent to a user's URL, background jobs on the owner's model, starter code follows the
  model without the key, account deletion. Mutation-checked (local refusal, server key, request and
  job activation, export). Backend **532 passed, 9 skipped**; ruff/mypy clean on changed files.
- Frontend: 4 component tests + new browser spec `e2e/model-choice.spec.ts` (save a key → only
  `…9876` shown, never in the page; local model → test → save → chat answered by it → reset).
  Passes with a stand-in Ollama and **with the real Ollama + qwen2.5:3b** (`E2E_REAL_OLLAMA=1`).
  All 6 browser specs, 134 unit tests, typecheck, lint, build pass.
- Scripts: `-CheckOnly` / `CHECK_ONLY=1` on this machine; first run and re-run in a sandbox copy
  (writes `.env` once, keeps it, finds the installed model via the API, starts the app stub).

#### Not verified
- Any hosted provider live (no keys here): request shapes are checked with mock transports only.
  Free-tier details change — the UI says to check.
- The full first-time install path of the run-local scripts (pip/PyTorch/npm downloads) on a fresh
  machine, and the macOS/Linux script outside Git Bash.

### Session 11 (continued): the retrieval gate, and generation improvements

- **The gate** ("retrieve only when needed", this project's own idea, as a *starter*): plan names
  *Adaptive / selective / conditional / gated retrieval, retrieve only when needed, on-demand
  retrieval* → a gated generator (`Plan.gate`; trained systems like Adaptive-RAG stay unmapped).
  `config.json` gets a `gate` block: policy **`abstain`** (default, no tuning — closed-book first,
  retrieve only if the model says it can't answer; the closed-book reply is cached, so a known
  question costs one call and a retrieved one two) or **`retriever`** (retrieve only when the top
  first-stage score is ≥ `threshold` standard deviations above the candidates' mean —
  `Pipeline.confidence`, scale-free, averaged over fused scorers; ∞ with one candidate). New metric
  **retrieval rate** (evidence family). README explains both policies, says to tune the threshold on
  validation only, and names the missing *always* (RAG) / *never* (Closed-book) baselines.
- **Generation**: replies that only decline ("The passages do not contain…", "I don't know") →
  `unanswerable` (needed by the gate; "No" and "Unknown" are left alone — they can be answers);
  cleaning applied on read so cached replies follow `clean()`; **answer styles** — MS MARCO's loader
  sets `answer_style: "sentence"` (one-sentence prompt, ≥ 128 tokens); **retries** for 429/5xx and
  dropped connections (2, doubling pause, honours Retry-After; refused connections, timeouts and
  404 are not retried); **`run_experiments.py --estimate`** counts uncached calls and prompt tokens
  without calling the model or writing results (upper bound for gates). Prompt label `qa-v2`.
- Runner: metrics on passage-less datasets no longer vanish (only retrieval metrics are removed).

#### Verified
- 24 more tests (abstention phrases ±, cache re-cleaning, sentence style, MS MARCO style, retries and
  what is never retried, estimate counting, both gate policies end to end, z-score by hand, bad gate
  config, estimate writes nothing). Mutation-checked: an always-retrieving gate, an estimate that
  skips the gate's second call (first version of that test missed it — the RAG baseline masked it;
  fixed), retries off. Backend **510 passed, 9 skipped**; ruff/mypy clean on changed files.
- **Real model (qwen2.5:3b)**, gate vs RAG vs Closed-book on toy / SQuAD / HotpotQA / MS MARCO sample
  rows: `--estimate` said 28 calls, the run made 28. MS MARCO sentence answers: RAG F1 0.34 vs
  closed-book 0.14; gate retrieved 1 of 2. **SQuAD: the abstain gate never retrieved (EM 0 vs RAG
  1.0)** — closed-book the model confidently answered "San Francisco 49ers" to all four Super Bowl 50
  questions. The self-knowledge gate is only as good as the model's calibration; the README warns
  ("watch the retrieval rate"). Found while testing: the z-score ignores absolute strength (one weak
  lone match = one strong one; all toy questions score √3) — documented in `confidence()`.
  **2–4 examples per dataset: machinery, not findings.**

#### Next
- A better decision signal is the research question itself (e.g. combine retriever confidence with
  the model's answer, sample-consistency, or a learned probe) — the user's to choose.

### Session 11: 2026-10-09 — starter code: answer generation (the "G" in RAG)

Picked up from a session cut off by a rate limit (its notes were in `promptt.txt`; the metrics half
was uncommitted and is kept).

- **`starter/generation.py`** (ships with the starter; standard library only): a `Generator`
  over the platform's providers — **Ollama** (`/api/chat`) and **OpenAI-compatible**
  (`/chat/completions`). Greedy
  decoding; a fixed short-answer prompt (`qa-v1`) that says `unanswerable` when the
  passages don't hold the answer; a closed-book prompt when there are no passages; `clean()` strips only
  "Answer:", `[n]` markers and `<think>` blocks. **Disk cache = log** (`cache/generations.jsonl`: prompt,
  raw reply, tokens, seconds, stop reason), keyed by provider/model/URL/settings/prompt text: seeds and
  reruns are free, an interrupted run resumes. Failures raise `GenerationError` with the fix; keys only
  from the environment.
- **Plan mapping**: `resolve()` now returns `Plan(stages, rerank, generate, unmapped)`. RAG names
  (*RAG, Retrieval-augmented generation, standard/vanilla/naive RAG, answer generation*) → generation
  over the pipeline (BM25 by default, like a reranker); *Closed-book / No retrieval / LLM only* → a model
  without retrieval (the usual adaptive-retrieval baseline). Self-RAG, FiD etc. stay unmapped (trained
  systems).
- **Metrics** (`metrics.py`): `contains` (whole-word, for wordy LLM answers; next to EM, never instead),
  `groundedness` (share of answer content words found in the passages it was given — documented as a
  lexical proxy, *not* faithfulness), `abstention rate`; "faithfulness"/"hallucination" give a clear
  "needs an entailment model or a judge" instead of a number.
- **Runner / systems**: systems gain `evidence()` (passages the answer came from; extractive sanity
  systems → grounded 1.0 by construction); `rank()` may return `None` (closed-book) → retrieval metrics
  `todo`, not 0; a metric no example could score → `todo` row with the reason; a model that can't be
  reached → `error` row with the fix and "rerun to continue"; per-system generation stats printed.
  A RAG system on a passage-less dataset (TriviaQA, NQ-Open) → `todo` (found in the real run: it was
  silently answering closed-book under a RAG label).
- **Codegen**: `config.json` gets a `generator` block copied from the platform's LLM settings (never the
  key; `fake` → Ollama); README step 5 explains generation (provider, keys, cache, cost, `--limit 50`,
  Contains/Groundedness, top_k for multi-hop); routes pass settings to codegen.

#### Verified
- 26 new tests (`tests/test_starter_generation.py`): each provider against a local stand-in server
  checking path, headers and body, auth errors, cache keys and resume, config checks, whole
  generated RAG projects (EM 0 vs contains 1 on wordy answers, closed-book retrieval `todo`, 8 model
  calls for 3 seeds, unreachable model → `error` rows, TriviaQA → `todo`). Mutation-checked: dropping
  `fallbacks`, scoring closed-book groundedness as 0, and disabling the cache each fail tests.
- Backend **483 passed, 9 skipped**; ruff/mypy clean on the changed files.
- **Real model (qwen2.5:3b, CPU, Ollama)**: opt-in test passes (≥ 3/4 toy questions; off-topic →
  `unanswerable`). Whole generated project (RAG vs BM25 vs Closed-book) on the toy set and the real
  HotpotQA / SQuAD / TriviaQA sample rows: SQuAD RAG EM 4/4; ~3–4 s per answer with 3 passages,
  ~26 s with 10; seeds 1–2 served from the cache. **HotpotQA: RAG abstained 4/4 with top 3** — BM25
  missed the second-hop paragraph (e.g. no Scott Derrickson paragraph); with all 10 paragraphs
  abstention 0.5, EM 0.25 (one wrong answer). README now says to check recall at top_k first.
  **4 examples per dataset: these numbers show the machinery, not a finding.**

#### Not verified
- OpenAI-compatible generation against live services (no keys here) — request shapes are
  checked through stand-in servers only.
- The real `datasets` download path (not installed); groundedness is lexical and misses false claims
  built from true words.

#### Next
- The "retrieve only when needed" **gate** component (matches this project's own idea): skip
  retrieval when first-stage scores are flat, generate closed-book otherwise; compare with always-RAG.
- Roadmap items: answer feedback, HyDE / query decomposition, better introductions from a small model.

### Session 10: a runnable YourApproach (components + plan-name mapping)

- **Decision:** a model can't write the user's novel idea (and a 3B model's code is unreliable), but most
  of an approach is known parts, so the starter now ships **real components** and maps the plan onto them.
- `starter/components.py` (standard library at import; models load lazily): **BM25** (Okapi, Lucene IDF,
  hand-calculated in a test), **DPR** (public NQ checkpoints, pooled output, dot product), **Contriever**
  (mean pooling per its model card), a **sentence-transformer** (BGE-small, with its query instruction),
  **cross-encoder reranker** (MiniLM, top 20), **reciprocal rank fusion**, a `Pipeline`, an **extractive
  reader** (only ever returns text from the passage). Model ids verified to exist on Hugging Face.
- **Plan-name mapping** (`resolve`): BM25 / DPR / Dense Passage Retrieval / Contriever / Contrastive learning
  (→ pretrained Contriever, noted) / Dense retrieval / Hybrid retrieval (BM25 + dense, RRF) / Reranking /
  Cross-encoder; anything else is reported as **not implemented, by name**.
- Generated `systems.py`: baselines that map are runnable `PipelineSystem`s (public checkpoints, not
  retrained — stated); `YourApproach` becomes a **first runnable version** with a marked "Your idea goes
  here" override of `rank()` (works: tested), its docstring/README say it is *not the user's idea*, and every
  `results.csv` number carries `starter pipeline: …` (+ `NOT implemented (no component): …`). If nothing maps
  it stays a TODO stub. README step 5 rewritten (what runs, what is yours, four ways to start) and warns
  about first-run model downloads only when models are involved.
- **Verified with real models** (opt-in `RUN_MODEL_TESTS=1`): BGE + cross-encoder hybrid pipeline, BGE,
  Contriever and DPR each rank the relevant toy passage first (≥ 3 of 4; DPR/Contriever downloads took ~7 and
  ~15 min). A whole generated project (hybrid + rerank vs BM25 / DPR / Contriever) ran on the **real MS MARCO
  sample rows** in 46 s and produced numbers for all systems. **4 queries: the numbers mean nothing**
  (e.g. Contriever recall@1 0.0, "Your approach" MRR 0.75, DPR 0.625) — it shows the machinery, not a finding.
- Tests: BM25 / RRF by hand, pipeline behaviour (rerank depth, fusion, ties, empty), name mapping (10 cases),
  whole generated projects (runnable, partially mapped, stub), the override mechanism, download note.
- **Not verified:** that a user's real hypothesis maps well — the table is small (10 names) and "Contrastive
  learning → Contriever" is a judgement; DPR/Contriever were run through their wrappers, not compared with
  published numbers on the paper's data; no GPU path; extractive answers are weak (exact match is 0 on MS MARCO,
  whose answers are free text).

### Session 10 (later): starter-code dataset loaders

- Verified the datasets' real schemas through Hugging Face's dataset-viewer API (no downloads) and saved
  real sample rows as test fixtures (`tests/fixtures/hf_rows`). Loaders in the starter's `data.py`:
  SQuAD, **MS MARCO v2.1** (10 candidates per query, `is_selected` = relevant; queries with none left
  out), **HotpotQA distractor** (title + sentences per paragraph; supporting-fact titles = relevant),
  **TriviaQA rc.nocontext** and **NQ-Open** (answers only, no passages). Loader registry with notes shown
  in the generated README; names matched loosely; BEIR stays a pointer; FEVER has neither loader nor
  pointer (schema not verified).
- **Integrity fixes in the runner:** a dataset without passages + a retrieval metric now gives `todo` rows
  with the reason instead of a 0 that looks like a result (mutation-checked); examples with no accepted
  answer are skipped for answer metrics instead of scoring 0; a missing `datasets` package or no network
  becomes a `todo` row naming the cause; generated sanity systems don't crash on passage-less examples.
- Tests: loaders on the real rows through a stand-in `datasets` module; whole generated projects run for
  TriviaQA (answers ok, recall `todo`) and MS MARCO (recall numbers). **Not run:** the real `datasets`
  download path (not installed here) — the field mapping is verified, the download is the library's.

### Session 10: 2026-10-04 — Project Builder tried on two new papers; guidance and arXiv import

#### Test: Research Project Builder, real models, papers not in the library
- Papers: Contriever (arXiv 2112.09118) and Self-RAG (2310.11511), downloaded from arXiv, uploaded
  to a fresh database (throwaway server, `RERANKER_PROVIDER=none` for RAM; qwen2.5:3b on CPU,
  real BGE embeddings and NLI checker). Idea: *QA over scientific papers without labelled data
  that knows when retrieval is needed.* Both papers processed in ~60 s with correct titles/years.
- Flow, timings, what came out:
  - **Questions** (99 s): 6 suggestions, all linked to passages of both papers; two were generic
    ("knowledge distillation") and one was cut in half at "Mr." (bug, fixed below).
  - **Background review** (8 min): honest but thin — every overview sentence was removed as
    unsupported ("Not enough evidence"), the one theme paragraph covers only Self-RAG. Chronology,
    comparison table (datasets / metrics per paper) and the gaps section were correct.
  - **Gaps** (9 s): one stated gap (a Self-RAG limitation), four weak directions; nothing about the
    idea itself (adaptive retrieval + unsupervised retriever), which two papers can't show.
  - **Methods** (instant): sensible, counted per paper (Natural Questions, TriviaQA, FEVER, DPR,
    Contriever, Recall@k …) with some noise ("Learning rate warmup" as a method).
  - **Experiments + milestones** (instant): 3 main comparisons + ablation + analysis, milestones to
    the deadline. **Outline** (173 s): introduction one sentence, off-topic (Self-RAG's inference
    algorithm); related work Self-RAG only; method / experiments scaffolds correct. Exports (MD,
    DOCX, LaTeX + BibTeX) all work; `\cite` keys match `references.bib`.
- **Verdict:** the guided flow works end to end and never invents (unsupported text is dropped and
  scaffolds are labelled), but with a 3B model and two papers the *generated* parts are thin; the
  value is in the structure, the counted methods and the exports.

#### Delivered
- **Project guidance**: `guidance` on every project response (first unfinished step + notes);
  "Next:" card on the project page with a "Go to …" link. Warns when no collection is linked or the
  project has fewer than 4 papers (`MIN_PAPERS`).
- **arXiv import** (`services/arxiv.py`, `POST /documents/import/arxiv`, Papers page → "Import
  from arXiv"): id or link → PDF + arXiv's title, authors, abstract, date, DOI; fields stay
  protected from reprocessing with provenance `arxiv`. Fixed hosts only (arxiv.org,
  export.arxiv.org), https only, redirects elsewhere refused, size cap, `LOCAL_ONLY` refuses,
  duplicates by arXiv id skipped, one request per paper in the UI.
- **Step-by-step guide for every project step** (`services/projects/guide.py`, `GET
  /projects/{id}/guide/{step}`, "How this step works" panel above each step, collapsible): why,
  numbered actions with their reasons, what you should end up with, how to check it, common
  mistakes, and "your project right now" (restates saved choices). Hand-written, not generated.
- **Starter code from the plan** (`services/projects/codegen.py` + `starter/`, 7th nav item "Starter
  code", `GET /projects/{id}/code`, `export?format=code` zip): `metrics.py` (accuracy, EM, F1,
  recall / precision / hit @k, MRR, nDCG; hand-checked tests), `data.py` (toy set, SQuAD loader,
  pointers for Natural Questions / TriviaQA / MS MARCO / HotpotQA / BEIR — verify ids before use),
  `run_experiments.py` (`--smoke`, `--only`, `--limit`; `results.csv`, `summary.md`, predictions),
  generated `systems.py` (sanity systems finished; your approach + baselines are stubs naming the
  papers that use them), `config.json`, `README.md` (10-step walkthrough with what to expect and a
  trust checklist), `test_pipeline.py`. Not model-written; anything unimplemented — system, metric
  or dataset — yields a `todo` row with the reason, never a number.
- **Project page**: choose / change the project's collection (the guidance advised adding papers
  but the link could only be set at creation).
- **DOI support** (`services/doi.py`, `services/safe_fetch.py`): `POST /documents/import` (replaces
  `/import/arxiv`) takes arXiv ids / links and DOIs; an arXiv DOI (10.48550/arXiv.…) imports in full,
  any other DOI answers with its title and "upload the PDF, then Fill from DOI" (a DOI has no PDF to
  fetch). `POST /documents/{id}/metadata/doi` + **Fill from DOI** button in Edit details fill title,
  authors, abstract, date, venue, DOI from Crossref (one fixed host, strict DOI pattern, https,
  size cap, `LOCAL_ONLY` refuses; protected from reprocessing; provenance `crossref`). The fixed-host
  fetch from the arXiv importer moved into `safe_fetch` and both use it. **Decision (asked):**
  metadata + arXiv DOIs only; Unpaywall / arbitrary PDF hosts left out (needs an SSRF guard).
- **Zip import** (`services/zip_import.py`, `POST /documents/import/zip?collection_name=`, Papers page →
  "Import zip"): every PDF / DOCX / HTML / Markdown / text file in a folder-zip goes through the normal
  upload path; optional new collection from the zip's papers. Result lists imported, failed (with
  reason) and skipped (with reason). Hostile-archive defences: entry names are only labels (last
  segment) and never paths; ≤ 100 papers; per-entry limit and a total limit on bytes *actually read*
  (declared sizes aren't trusted); expansion ratio > 100 skipped; password-protected and nested
  archives skipped; the zip itself has its own limit (`MAX_ZIP_SIZE_MB`, 200).
- **Deployment catch** (found while committing, from the deployment guide): the bundled nginx caps bodies at 100 MB,
  which would have rejected zips between 100 and 200 MB before the app saw them. Added a dedicated `location =`
  for the zip route (200 MB, 300 s timeout), `MAX_ZIP_SIZE_MB` in `.env.example`, and the import / zip
  defences in `docs/SECURITY.md`. The Docker stack itself still hasn't been run (no Docker here).
- **The outline covers every project paper** (`projects/generate.py`): a paper the introduction's main
  search missed gets its own search (≤ 8 papers, 2 passages each); related work adds, for every paper
  the review text didn't mention, its best *checked* statement with citation (contribution →
  takeaway → problem → method → results; fully supported before partly supported, marked as such),
  or "No statement from this paper passed the check, so it isn't cited here"; the comparison table's
  "Approach" shows what each paper proposes (it repeated the question when there was one theme).
  A mutation check (coverage switched off) makes the introduction test fail, so it does test it.
- **Found by looking at real Crossref answers** (canned tests had missed both): the title is split
  ("Optuna" + subtitle "A Next-generation …") and venue / names come HTML-escaped ("&amp;").
- Browser spec `e2e/doi-metadata.spec.ts` (button state, refusal reasons, axe light + dark) found a
  pre-existing contrast problem: the "(one per line)" hint in Edit details was `text-subtle`.
- **Fixes from the test**: sentence splitter no longer breaks after Mr./Dr./e.g./Fig./…
  (affects chat, summaries and reports too); titles cut at a word boundary (`shorten`).
- Roadmap: post-launch additions and the status of the old suggestions (`docs/ROADMAP.md`).

#### Verified
- Backend 368 passed (+4 opt-in): 28 new (guidance rules, API field, splitter, `shorten`, id parsing
  incl. look-alike hosts and metadata-service addresses, import keeps arXiv metadata through
  processing, duplicates, partial failure, LOCAL_ONLY, redirect / HTTP downgrade / 503, oversize,
  non-PDF). Frontend 117 (5 new). Ruff, oxlint, tsc clean; mypy shows the same 44 existing errors.
- Importer run against the live arXiv API (DistilBERT 1910.01108: 4 authors, date, 436 kB PDF;
  unknown id → "no paper with this id"). The unit tests had caught two of my own bugs first
  (arXiv's error entry id is `…/api/errors#…`; an explicit `None` in the metadata patch).

- Browser: new spec `frontend/e2e/project-guide.spec.ts` (production build, deterministic API):
  create project → next-step card → guide on all 7 steps (collapse works) → Starter code (files,
  README, systems.py, zip download starts with PK) → axe light + dark → 390 px no overflow → no
  console errors. It found three real bugs, fixed: (1) **`useReport('')` requested `/reports/`**
  on the Gaps step, which the API redirects to its own origin and the production CSP blocks
  (existing bug; `enabled: id !== ''` + test); (2) secondary text in the *selected* step / file
  item was `text-subtle` on the tinted background (dark-mode contrast; existing in the step
  nav); (3) the generated project's own smoke test failed when the plan had no experiments
  (smoke now uses a built-in default experiment with retrieval metrics).

#### Real-model re-run of the Contriever + Self-RAG project (qwen2.5:3b, review 8 min)
- Both papers now appear in the outline's sources (before: Self-RAG only); related work names
  Contriever with "No statement … passed the check" — accurate: its summary had **no** usable
  statements in that run (an earlier run did produce a takeaway; the 3B model's output varies);
  the Approach column reads `['', 'SELF-RAG']`.
- **Not solved:** the introduction is now long and weak — twelve subject-less sentences ("introduces
  the context of …") from Contriever's passages, almost none cited, though labelled "Well supported".
  That is the 3B model writing from more evidence; a prompt change would have to be measured first
  (an earlier "name the paper" prompt did not help). Roadmap item.

#### Verified (final)
- Latest full run: backend 405 passed (+4 opt-in), frontend 130, browser 5/5 (zip import spec added;
  axe light + dark). 20 DOI + 8 zip + 3 coverage tests among them. The earlier line below is the
  starter-code run.
- Backend 375 passed (+4 opt-in): generated project written to disk and actually run — smoke test,
  its own pytest suite, a full run where stubs give only `todo` rows, a dataset without a loader
  fails loudly with a pointer, empty plan still gives working code, zip contents, every step guide
  complete and reflecting the project. Frontend 125; e2e 3/3 (accessibility audit included).
  Ruff, oxlint, tsc clean; mypy shows the same 44 existing errors.

#### Not verified
- The importer was not run end to end through the server with real arXiv (unit tests with canned
  responses + a live fetch of the module only). The generated starter project was run on the toy
  data only — SQuAD loading needs `pip install datasets` and a download and was not exercised.
- The guide is text written once; it has not been reviewed by a researcher for domain accuracy.
- Nothing was committed.

#### Known issues found, not fixed
- Outline / related work / BibTeX can cite only one of the project's papers (retrieval for the
  introduction isn't balanced across papers); comparison table "Approach" repeats the question when
  there is a single theme; Contriever gets no "proposes" entity; authors empty on parsed PDFs
  (arXiv import avoids it).

### Session 9 (continued): Phase 16, 2026-10-02 — polish, demo mode, deployment ✅

#### Delivered
- **Demo mode**: "Try sample papers" on the empty library and home page (`POST /demo/sample-papers`,
  idempotent) loads the three synthetic sample papers through the normal pipeline into a
  "Sample papers" collection. Demo copies say "Synthetic sample paper … not a real
  publication" on every page and drop the made-up arXiv ids (they could match real, unrelated
  papers) and e-mail domains.
- **Accessibility audit**: axe-core (WCAG 2.1 A/AA) on 14 pages in light and dark themes plus a
  paper page, in the browser test suite and CI. Found and fixed: secondary text 4.0:1 on every
  light page (`--text-subtle` → 4.6:1+), white on light red 2.75:1 on the dark-theme danger
  button (new `--on-error`), colour-only links. `docs/ACCESSIBILITY.md`.
- **Polish**: the home page's "Coming to your workspace" section had become an empty list now
  that every feature shipped → "What you can do" with all features; dead planned-feature page
  and nav flag removed; the redundant "Upload Multiple" button (same action as "Upload Paper")
  replaced by "Try sample papers".
- **Bug found in the walkthrough**: a paper being processed showed "about 3 h 23 min remaining"
  — its progress schema skipped the UTC marking of SQLite timestamps, so browsers read them
  as local time (+5:30). Fixed, plus a test that every response schema with datetimes marks
  them UTC.
- **Performance**: main bundle 117 kB gzipped, every feature page lazy-loaded; numbers recorded,
  no further splitting needed.
- **Deployment guide** (`docs/DEPLOYMENT.md`): services, requirements (8 GB CPU-only works),
  first deployment and `.env`, HTTPS with Caddy (SSE unbuffered), demo instance, monitoring,
  backups and restore, upgrades, scaling, security checklist. `.env.example` gained the
  Phase 13–15 settings. README rewritten for the finished state.

#### Verified
- Backend 340 passed (+4 opt-in): demo papers (processed, collection, idempotent, labelled,
  no arXiv id), UTC schemas. Frontend 112; browser: end-to-end + accessibility (1.2 min).
- Walkthrough: new account → empty home with "Try sample papers" → three papers processing in
  the library → paper page; no console errors.

#### What's left (not in the 16 phases)
- Run the Docker stack (incl. Prometheus/Grafana) on a machine with Docker; CI builds the images.
- Multi-factor auth and email verification; per-user limits shared across API replicas.
- Hand-written evaluation questions (paraphrased) to judge dense retrieval fairly — the
  model-drafted set favours BM25.

### Session 9 (continued): Phase 15, 2026-10-02 — testing & security ✅

#### Delivered
- **Cross-tenant matrix** (`tests/test_tenant_isolation.py`): driven by the OpenAPI schema,
  another user requests the owner's resource on every route with a path id (67 route/method
  pairs): reads/deletes must 404, writes must never succeed, owner's data intact afterwards;
  a new route fails until the fixture covers it. Found: `DELETE /documents/{id}/bookmark`
  answered 204 for another user's paper (harmless, now 404).
- **Browser end-to-end test** (`frontend/e2e`, `npm run e2e`, CI job): register → upload →
  processed → ask → cited, checked answer → sources, against the production build with its
  CSP and an API with a fresh DB and deterministic models (`backend/scripts/e2e_server.py`);
  any console error fails it.
- **Startup recovery** (`workers/recovery.py`): inline jobs interrupted by a restart resume;
  after 3 interruptions they fail with their paper/report/run (per-kind `on_interrupted`
  hooks), so nothing stays "processing" and a crashing file can't loop.
- **Privacy**: full export (`GET /users/me/export`, Settings → Download your data: JSON of
  everything owned, secrets excluded, plus original files); security activity
  (`GET /users/me/activity`, Settings). **Bug found**: deleting an account left files, page
  images and vectors on disk — now each paper is deleted through the normal path first.
- **Hardening**: DOCX zip-bomb limits (unpacked size, compression ratio); CSP for the SPA
  (nginx + `vite preview`) and the API; nginx headers in one include (the `/assets/` location
  had been dropping them); optional `METRICS_TOKEN`; per-user cap on concurrent answers
  (429); `pip-audit` + `npm audit` in CI (clean).
- `docs/SECURITY.md` rewritten as a threat model with controls, tests and known limits.

#### Verified
- Backend 338 passed (+4 opt-in): recovery (resume, give up + subject failed + retry,
  stuck document + queued job), tenant matrix, export contents and no secrets, deletion
  removes files and vectors, zip bombs, CSP headers, metrics token, concurrency cap.
- Frontend 112 + E2E (23 s). Real data: export of the 12-paper walkthrough library = 11.7 MB
  zip with all originals; activity shows the export; Settings mobile/dark without overflow.
- Walkthrough found the sessions list unbounded (~70 sign-ins from test scripts) → scrolls.

### Session 9 (continued): Phase 14, 2026-10-02 — usage, caches, observability ✅

#### Delivered
- **Usage and cost tracking** (`services/usage.py`): every model call goes through
  `MeteredLLM`; the job runner names the feature from the job kind, chat passes its own.
  `llm_usage` rows (tokens — estimated when a stream stops early —, latency, first-token time,
  cost priced at call time, status). Per-model prices: `LLM_PRICES`. Migration `cd8784126755`.
- **Two-tier cache** (`core/cache.py`): process LRU + Redis when configured (shared by API and
  workers, survives restarts; Redis failure → local only, never an error). Query embeddings and
  reranker scores moved onto it, with hit/miss counters; `CACHE_ENABLED=false` for benchmarks.
  Search results deliberately not cached (repeat searches are already ~70 ms).
- **Semantic answer cache** (`rag/answer_cache.py`): reuses an earlier, checked answer for a
  near-identical first question when the same passages are found; labelled in chat with
  "Answer again" (`fresh: true`). Guards measured first: cosine alone can't separate "Does DPR
  outperform BM25?" from its reverse (0.990) — numbers and names must match in order too.
- **Usage & performance page** (`/usage`): totals, calls per day (chart + table), by feature and
  model (tokens, cost, latency p50/p95, first-token p50), latency per stage (estimated from
  histogram buckets), cache hit rates.
- **Prometheus/Grafana** compose profile `observability` with a provisioned dashboard;
  `/metrics` adds usage series for all processes from the database.
- Docs: `docs/OBSERVABILITY.md`.

#### Verified
- Backend 328 passed (+4 opt-in skipped): usage per feature and pricing, personal usage,
  performance endpoint, `/metrics` exposition, early-stopped streams, histogram percentiles,
  two-tier cache with a fake Redis (sharing, LRU, failure fallback, off switch), answer reuse
  and every guard (other numbers, follow-ups, fresh, disabled, reordered passages, failed
  check, UTC timestamps). Frontend 111 (usage page, reused notice + Answer again). Lint, types,
  build clean.
- Browser walkthrough: usage page with tooltip, reused answer with Answer again, mobile + dark
  without overflow, no console errors. Compose/Grafana files parsed; containers not run (no
  Docker on this machine).

#### Real-model walkthrough — found and fixed
- Matching the cached answer's passages *in order* missed a plain case change (positions 6–8
  swapped) → match the set; the reused answer is shown with its own numbering.
- The case-insensitive embedder scored a lowercased repeat 1.0 and the tie went to a newer
  answer the checker had marked unsupported → only checked answers are reused, best first.
- "Asked 6 hours ago" for a minutes-old answer: SQLite naive datetime → sent as UTC.
- Result: reused answer in ~2.5 s instead of 40–90 s; the 33B-vs-65B question correctly not
  reused. Metering showed chat time is almost all time-to-first-token (56 of 59 s, prompt
  reading on CPU).

### Session 9: Phase 13, 2026-10-02 — evaluation ✅

#### Delivered (`services/evaluation/`, `pages/evaluation/`)
- **Datasets** of questions with expected evidence stored as character spans plus a quote
  (survive re-chunking and re-processing). Questions added by hand (search passages, tick
  the ones that answer) or drafted by the model from sampled passages — drafts stay
  "unverified" and don't count until accepted.
- **Retrieval metrics**: Recall@K, Precision@K, MRR, nDCG@K (a span counted once), paper
  recall@K, K ∈ {1, 3, 5, 10}; checked against hand-worked cases and scikit-learn.
- **Answer metrics** (RAG runs, up to 25 questions): faithfulness and citation correctness
  from the NLI checker (deliberately not an LLM judge), context recall / precision, answer
  relevance (embedding similarity); insufficient-evidence rate.
- **System metrics**: search and total latency p50 / p95, throughput, tokens, cost (configurable
  prices; 0 for local models).
- **Runs** override retriever, reranking, top-k, rerank candidates, RRF k and context size on a
  copy of the settings and snapshot the index, reranker, LLM and verifier they ran against.
- UI: **Evaluation** page — Runs (start a run, results table), Compare (2–4 runs: grouped bar
  chart with a validated colour palette, table with differences, questions where the runs
  disagree), Datasets (add, draft, accept/reject); run page with per-question top passages,
  answers and latency. Migration `0bf40abdcd54`. Docs: `docs/EVALUATION.md`.

#### Verified
- 7 unit tests (metrics, sklearn nDCG cross-check, question parsing, prose filter) and 4 API
  tests (comparing configurations, RAG scoring, generated questions need review, privacy and
  deletion); 4 frontend tests. Backend 308 passed (+4 opt-in skipped), frontend 108, build,
  lint and types clean.
- Browser walkthrough (Playwright + Chrome): runs, compare with hover tooltip, run detail,
  datasets with passage search, mobile and dark mode without page overflow, no console errors.

#### Real-model walkthrough (12 papers, qwen2.5:3b, CPU)
- Drafted 12 questions in 85 s; accepted 8. Two were about figure-axis text → the sampler now
  skips passages where under half the words are plain words (measured: 26 of 537 passages, all
  figure or table text). Added 2 hand-written questions → 10.
- Retrieval A/B: reranking lifts MRR 0.75 → 0.85 (~2 s per query on CPU); BM25 does best on
  model-drafted questions (they reuse the passage's words — a known synthetic-set bias); RRF
  k = 10 vs 60 changes 5 of 10 top-5 lists but not the relevant passage's rank.
- **The evaluation found three problems in answer checking**, each confirmed before fixing:
  - A verbatim claim scored 0.19 against its 60-word window and 0.99 against its sentence →
    the shared checker now gives unsupported cited claims a sentence-level second look
    (offline A/B on the stored answers 0.133 → 0.272, nothing lowered). Benefits chat,
    summaries and reports too; costs ~3 s per answer.
  - Faithfulness counted correct uncited sentences as 0 → now counts support by any passage,
    as chat's verdict does.
  - 3 of 10 answers copied the prompt's placeholder ("<statement from passage 1> [1].") →
    removed for every answer (`strip_placeholders`); content wrapped in "<…>" is unwrapped.
  - Re-run: faithfulness 0.13 → 0.67, citation correctness 0.22 → 0.44.
- UI fixes from the walkthrough: tooltip positioned against the rendered chart; passage search
  for evidence skips reranking (2 s → ~50 ms) and shows a searching state; token/cost rows
  only when a RAG run is compared.

#### Next
- Phase 14: observability, caching, cost tracking.

### Session 8: Phases 11 and 12, 2026-10-02 — reviews, gaps, deep research; project builder ✅

#### Delivered — Phase 11 (`services/analysis/`)
- **Reports** (one table, four kinds, one `report.generate` job): literature review, research
  gaps, potential disagreements, deep research. Every analysis works from *paper digests*: the
  statements of each paper's summary that its NLI check supported, with their passages;
  missing summaries are written first, one paper at a time.
- **Literature review**: papers from a selection, a collection or a topic search (a paper
  qualifies only if a keyword retriever matched it — dense search returns something for any
  topic; caught by a test) → grouped by embeddings and named → cited overview and theme
  paragraphs (every sentence checked) → chronology and comparison table from the knowledge
  layer → disagreements → gaps and directions.
- **Gaps** labelled "Stated by the authors" (grouped limitations / future work) or
  "System-generated synthesis" (untested method × dataset combinations, conflicting findings,
  LLM directions that must cite a numbered gap).
- **Disagreements**: statement pairs from papers sharing a named entity, NLI contradiction both
  ways (a polarity rule with the lexical test verifier); both claims, sources, and setup
  differences; never a verdict.
- **Deep research**: plan → search → answer → refine once → conclusion; one read-only search
  tool; step / token / time limits checked before every step; open questions reported; trace.
- Editing (marked "not re-checked") and export to Markdown, Word and PDF.
- UI: **Reviews & Research** page and report page (stage progress, sections by kind, gap
  labels, disagreement cards, agent trace, edit, export). Migration `b5256dcc7bfe`.

#### Delivered — Phase 12 (`services/projects/`, added at the user's request)
- **Research Project Builder**: idea → research question (suggested from passages, cited and
  checked) → background (a Phase 11 review) → gap & hypothesis (a gaps report; the user picks)
  → methods (datasets, models, methods, metrics the project's papers use, counted, with the
  papers; no model) → experiments (comparison per dataset, ablation, analysis) and milestones
  to a deadline (deterministic) → paper outline (introduction from passages, cited and checked;
  related work from the review with renumbered citations; method / experiments / conclusion
  as scaffolds from the user's plan). Suggestions are kept apart from the user's choices.
- Exports: plan as Markdown / Word; outline as LaTeX + BibTeX (.zip, `[n]` → `\cite{key}`).
- UI: **Research Projects** list and a six-step project page. Migration `f98287767cf4`.
- Roadmap renumbered: Evaluation is now Phase 13, …, deployment Phase 16.

#### Verified
- Phase 11: 6 API tests (review structure, citations, checks, summary reuse; topic search;
  gaps for a collection; disagreements; deep research trace and limits; edit + export to
  MD / DOCX / PDF; validation and privacy) and 6 unit tests (disagreements need shared setup
  and report differences; generic methods skipped in combinations; directions must cite a gap;
  planning and all three budget limits; exports). Backend 282 passed at the Phase 11 commit;
  frontend 99.
- Phase 12: 2 API tests (the whole flow idea → outline with exports, including LaTeX `\cite`;
  validation and privacy) plus the organization tests after moving the BibTeX helper (11
  passed); 5 frontend tests. Found by the tests: a shallow copy made project edits invisible
  to the ORM (now deep-copied); a privacy test reusing the owner's header by mistake.
- Lint and types clean for all new code.

#### Real-model walkthrough (qwen2.5:3b, after a memory reap and a restart)
- The first review run was stopped for low memory (I had run the test suite next
  to the API and Ollama). Restarted the API alone; summaries already written were reused, so the
  6-paper review took 4.5 min instead of ~25.
- **Found with the real model and fixed — each measured before adopting:**
  - *Reports barely cited:* 2 of 22 written sentences supported as written. Citations in
    parentheses "(5)", after titles, missing; claims the passages don't make ("edge devices and
    IoT"). Now: citation formats normalized; a sentence supported by a passage it didn't cite
    gets that citation ("set by the checker", labelled); a sentence citing several passages that
    no single one supports is checked against them together; a sentence nothing supports is
    removed and listed under its section (the page shows them; editing can restore). Re-run:
    every kept statement supported; deep research 8 of 8 (7 citations set by the checker).
  - *Thin text after removal:* a "name the paper in every sentence" prompt was A/B-tested and
    didn't help (13/29 kept either way) — not adopted. Most removals are cross-paper
    comparisons; checking them jointly helps when the model cites both passages.
  - *Directions all rejected:* the model copied the `<direction>` placeholder and put markers
    first → placeholders stripped, "Direction:" labels removed; 4 directions per run, each tied
    to its gap.
  - *Research questions: none* — the template "<question>? [2][4]" was filled with numbers
    ("1? [1][2][4]" ×5). Without the template the questions are good but uncited (A/B: 0 cited
    either way), so the system now links each to the passages it overlaps most with, labelled
    "related passages found by the system". Re-run: 4 specific questions.
  - *Deep-research plan:* "2 to 4 sub-questions" gave 1, 1, 4 on three requests (the single one
    dropped QLoRA from "How do LoRA and QLoRA …"); "exactly 3, numbered" gave 3, 3, 3. Adopted.
  - *Noisy gaps:* four "untested: T5 on MNLI / MRPC / QQP / RTE"; "GPT-4 on QQP" from one mention
    → one gap per method and per dataset; a method counts only if proposed here or used by two
    papers. Keyword gap titles ("layers, layer, adding") replaced by the statements.
  - Comparison table "Not reported" for 5 of 6 → falls back to the verified contribution.
  - "LoRA, as described in, injects …" left by moved citations → cleaned.
  - Project page overflowed by 377 px on a phone (step strip widened the grid column) → fixed.
- Browser (headless Chrome, real reports): reports list, review with removed-sentence disclosure
  and citation popovers, deep-research trace, Word export download, all six project steps,
  390 px mobile (no overflow), dark mode; no console errors.
- Project flow on a 4-paper collection: questions 68 s, background review 106 s, gaps 16 s,
  methods / experiments instant, outline 75 s; LaTeX zip exported.
- Final: backend 289 passed (+4 opt-in), frontend 104, lint and types clean (suites run with the
  servers stopped).

#### Known limitations
- With a 3B model, most cross-paper synthesis can't be verified one passage at a time, so reviews
  are short and factual rather than discursive; the removed sentences stay visible.
- Topic selection is lexical (it picked BERT and ColBERT for "parameter-efficient fine-tuning").
  Choosing a collection avoids it.
- Reports or uploads interrupted by a server kill stay "running" / "processing" (startup
  recovery: Phase 15).
- Project titles default to the idea's first sentence, which can be long (editable).

#### Next session: Phase 13 plan (evaluation)
1. Evaluation datasets: questions with expected passages (hand-written + generated from chunks,
   human-verified), stored per user.
2. Retrieval metrics (Recall@K, Precision@K, MRR, nDCG) for BM25 / dense / hybrid / reranked.
3. Answer metrics: faithfulness (claim support), citation correctness, answer relevance; with
   the known pitfalls of LLM-as-judge stated.
4. Experiments: named configurations compared side by side; dashboard.

### Session 7: Phase 10, 2026-10-02 — knowledge graph, entities, topics, timeline ✅

#### Delivered
- **Entity extraction** (`services/knowledge/extract.py`, deterministic, with evidence): a
  built-in catalog of 235 datasets / models / methods / metrics / tasks with aliases (reference
  facts like size and license only for 64 well-known datasets, shown as "built-in catalog"),
  plus discovery from the paper itself — Schwartz–Hearst acronym definitions, "Title: …"
  prefixes, "we propose / introduce / call X", "the X dataset". Model-size variants link to
  their family (BERT-large → BERT). Relation per paper: **proposes / uses / mentions** from
  where and how a name appears (method section, experiments, captions, "we evaluate on …";
  related work and the bibliography barely or not at all); up to 3 evidence sentences with
  page and section. Order-independent (discovery per paper, then matching against the
  library dictionary; re-match only papers containing a changed name). Runs at the end of
  processing (new progress stage) and lazily before knowledge reads.
- **Library snapshot** (`library.py`): in-library citations (DOI → arXiv id → title), authors
  with initials merged and parser artefacts filtered, institutions; cached per fingerprint.
- **Graph** (`graph.py`): NetworkX MultiDiGraph behind a `GraphStore` protocol (Neo4j-ready):
  overview by own weighted PageRank (top papers + entities connecting most of them),
  neighbours / expand, search, shortest path ("how are these connected?").
- **Topics** (`clustering.py`, hand-written NumPy): K-Means (k-means++, k by silhouette),
  average-linkage agglomerative, HDBSCAN (mutual reachability → MST → condensed tree → EOM);
  c-TF-IDF terms, shared entities, PCA map; names by the LLM in a `topics.name` job with a
  term-based fallback; stale detection.
- **Views / API**: `/graph` (+ neighbors, search, path), `/papers/{id}/knowledge-graph`,
  `/entities` (+ detail), `/documents/{id}/entities`, `/documents/{id}/related`, `/authors`
  (+ detail), `/timeline` (topic / author / venue / method filters, "first seen in your
  library"), `GET/POST /topics`. Migration `fe7e0eb3382e`.
- **UI**: Knowledge Graph page (Graph · Topics · Timeline · Datasets & methods · Authors);
  SVG graph with own force layout (deterministic, keeps placed nodes when expanding), zoom /
  pan / fit, type toggles as legend, search, expand, focus, path; topic map + cluster cards
  with quality explained; entity pages (catalog facts vs. evidence from papers, years,
  co-used entities); author pages (documented facts only); paper page: "Datasets, models &
  methods" card with evidence and a **Related** tab (citations in the library, shared
  datasets / methods, same authors, then semantic matches).
- Third synthetic sample paper (cites the other two, shares authors) for tests and demo.

#### Verified
- Backend: 270 passed by default (+4 opt-in), ruff/format clean, mypy clean for new code.
  New: 19 unit tests (catalog has no alias clashes, acronyms, proposes vs. prior work,
  relations, variants, order-independent merging; K-Means / agglomerative / HDBSCAN recover
  known groups and match scikit-learn exactly (ARI 1.0, same silhouette); PageRank; authors;
  citations; c-TF-IDF) and 8 API tests (extraction during processing, evidence, related work,
  graph overview / search / expand / path, timeline filters, clustering + naming job, stale
  topics, deletion cleanup, privacy). Frontend: 94 tests (12 new), typecheck, oxlint, build.
- Extraction tuned on **12 real arXiv papers** (LoRA, QLoRA, BERT, RoBERTa, DPR, ColBERT,
  RAG, ResNet, Transformer, ViT, Adapters, Prefix-tuning) parsed by our pipeline: every paper
  with a named contribution gets the right "proposes" (ViT doesn't: its title has no name
  and the abstract never says "we propose ViT"); datasets/metrics look right (e.g. DPR → NQ,
  TriviaQA, WebQuestions, CuratedTREC, SQuAD; top-k accuracy, exact match). ~70 ms per paper.
- Found and fixed on the way: false "proposes" (RoBERTa→BERT, ResNet→CIFAR-10, RALA→LoRA),
  "NQ" vs "Natural Questions" duplicates, junk dataset names ("NLP", "RE- ALNEWS"), appendices
  mislabelled "references" losing evidence, sentence-case catalog names ("Reciprocal rank
  fusion") never matching lowercase text, insert-order FK failure, migration `Text()` import.

#### Walkthrough (real papers, real models)
- Headless Chrome on 12 papers (9 real arXiv PDFs + 3 samples) with the real embedding model
  and qwen2.5:3b, run in two goes: the first attempt's servers were stopped
  for low memory, so the second used `RERANKER_PROVIDER=none SUMMARY_AUTO=false`, a lighter
  upload and an API restart to free the embedding model before topic naming.
- Topics → graph (search LoRA, details, path LoRA → *used by* RALA → *cites* DPR) → timeline
  (+ LoRA filter) → datasets → Natural Questions page (catalog info vs. evidence, used by DPR,
  RAG, RALA) → authors → QLoRA paper (entities card with evidence; Related: cites LoRA and
  RoBERTa by arXiv id, Adapters by title) → 390 px mobile (no overflow on all 4 views) → dark.
  Incremental re-matching seen live: a new paper re-matched 5–10 others in ≤ 1.2 s.
- Found with real data and fixed:
  - **Topic names swapped and identifier-style** ("Bert_Loading" for the retrieval topic):
    measured with the real model, one prompt for all clusters 0/6 grounded (same every run) vs.
    one prompt per cluster 6/6 ("Language Model Adaptation", "Document Retrieval",
    "Pretrained Language Models"). Adopted per-cluster naming, plus a check that keeps a name
    only if it shares words with its own topic more than with any other.
  - **Graph labels ~8 px and stacked on top of each other**: text now sized from the canvas's
    measured width, the layout stretched to the canvas shape, papers repel harder, and labels
    are placed greedily without overlap (the rest on hover / selection); fit padded for labels.
  - "Knowledge-Intensive NLP Tasks" accepted as an author (hyphenated title words) and
    affiliation lines with several institutions and e-mails ("Facebook AI †University of
    Washington … {…}@fb.com") used as one institution; paper cards now show the cleaned authors.
  - Path steps read "(is) uses method by" → reverse labels ("used by", "cited by").
  - Two unnamed `complementary` landmarks on the graph page → panel named "Graph details".

#### Known limitations
- A job interrupted by a server kill leaves its paper "processing" forever (seen when the first
  walkthrough's server was reaped). No recovery on startup yet → Phase 14/15.
- Author and institution data come from PDF metadata, which is weak on real papers: BERT,
  RoBERTa, ResNet and LoRA end up with no authors (the parsed names were title fragments and
  are filtered out), and a shared affiliation line can give an author a co-author's
  institution. Fixing multi-line title / author parsing is a Phase 2 follow-up; users can
  correct metadata.
- Clusters on 12 papers overlap (silhouette 0.17, shown as "overlapping"); ResNet and the
  Transformer paper land in the adaptation topic. With so few papers that's the embedding,
  not the algorithm (the algorithms match scikit-learn exactly).
- ViT gets no "proposes" (its title has no name, and the abstract never says "we propose ViT").
- `improves` / `contradicts` relations are left for Phase 11 (contradiction detection).
- PageRank uses a dense matrix: fine for hundreds of nodes, not tens of thousands.

#### Next session: Phase 11 plan (literature review & gaps)
1. Topic → retrieve → cluster (reuse Phase 10) → themes → chronology (timeline) → comparison.
2. Disagreements / contradiction detection between papers (NLI over aligned claims).
3. Research-gap detection; structured, cited review with an editor; export MD / PDF / DOCX.
4. Deep Research agent with step / token / time budgets.

### Session 6: Phase 9, 2026-10-02 — collections, tags, notes, bookmarks ✅

#### Delivered
- **Collections** (project / literature review / thesis / coursework): create (optionally with
  papers), edit, delete (papers stay), add / remove papers, collection page with papers, notes,
  **Chat** (a conversation limited to the collection's papers), **Compare** (when it has 2–5
  indexed papers) and **export to BibTeX / RIS** (citation keys like `wei2023lowrank`, arXiv
  as `@misc` + `eprint`, only metadata the paper has).
- **Tags** on papers (case-insensitive, created on first use, removed when unused, rename with
  clash check, max 20 per paper); **reading status** (to read / reading / read).
- **Notes** in Markdown (write / preview, Ctrl+Enter) on papers, collections, passages, figures,
  tables and chat citations; anchored notes keep page, offsets, quote and boxes.
- **Bookmarks** for papers, passages, tables, figures and citations (idempotent, one per thing).
- **Reader**: click a paragraph (PDF view hit-tests the paragraph boxes; text view clicks the
  paragraph) → "Bookmark" / "Note" bar; noted and bookmarked passages are outlined. Figures and
  tables have bookmark / note buttons; chat, summary and comparison source cards can save a
  citation.
- **Filters that affect retrieval**: library by collection / tag / reading status / bookmarked;
  search by collection and tag (resolved to paper ids before BM25 and dense search; facets list
  collections and tags); chat scoped to a collection.
- **UI**: Collections and Notes in the sidebar, Notes & bookmarks page, paper header (status,
  tags, Collections menu, bookmark), Notes tab, library chips + bulk "Add to collection",
  ⌘K "New collection". Migration `f466e706e7f7`.

#### Verified
- Backend 243 passed (+4 opt-in), ruff/format clean, mypy clean for new code. Frontend 82 tests,
  typecheck, oxlint, build. New: 10 organization API tests (privacy, cascades, filters in
  library / search / chat, export), BibTeX/RIS units, reader passage selection (PDF hit-test,
  marks), tag editor, notes, collection page; auth rate-limit regression.
- Headless Chrome (test model for the collection chat, so answers aren't real): library bulk
  add → new collection → note → BibTeX download → reading status, tags, bookmark → click a
  paragraph in the PDF → bookmark + note → outlined in the page → figure bookmark → Notes tab
  "Show" jumps to the reader → library filters (tag / bookmarked / to read) → search tag filter
  → Notes & bookmarks page → collection chat (sources only from its papers) → citation bookmark
  → ⌘K New collection → mobile + dark (no overflow). No console errors.
- Found and fixed:
  - **Logged out after ~10 page loads in a minute (Phase 1 bug):** `/auth/refresh` and
    `/auth/logout` shared the 10/min brute-force bucket with login, and every page load
    refreshes the session. Only credential endpoints (login, register, change password) keep
    the strict limit now; regression test included. Verified: 14 reloads, 0 sign-outs.
  - Reader page-number input stripped the letter "D" instead of non-digits (`/D/g` →
    `/\D/g`, a lost backslash from an earlier session).
  - Tag dedupe kept the last spelling ("#peft" over "PEFT"); citation keys split "Low-Rank"
    into "rank" (now "lowrank").
  - Library selection now allows any paper (bulk add to collection); the compare rule (2–5,
    indexed) moved to the Compare button with a reason.

#### Not yet verified / known limitations
- Passage = paragraph: there's no free text selection inside a paragraph (the PDF view is page
  images without a text layer).
- Tag colors are stored but not yet editable in the UI; tags are renamed/deleted via the API.
- The collection chat was exercised with the deterministic test model (scoping, not answers).
- "Highlight-to-ask" (send a passage to the chat) is not wired yet; notes and bookmarks are.

#### Next session: Phase 10 plan (knowledge graph & clustering)
1. Entity extraction (datasets, models, methods, metrics, tasks) from passages, with evidence.
2. Graph (NetworkX; Neo4j-ready interface): papers ↔ entities ↔ citations among uploaded papers.
3. Clustering of paper embeddings (K-Means / HDBSCAN / agglomerative) with LLM-named clusters.
4. Landscape view, timeline, author analysis; dataset / model pages.

### Session 5: Phase 8, 2026-10-02 — paper & methodology comparison ✅

#### Delivered
- **Shared extraction engine** (`summaries/engine.py: FieldExtractor`): the summary's map
  step (passages → labelled fields → citations → NLI checks) refactored so summaries and
  comparisons use the same code. Fixed on the way: the takeaway was checked without the paper
  title as context.
- **Comparisons** (`services/comparisons/`): 2–5 papers, two kinds — *papers* (problem,
  dataset, model, architecture, training, evaluation, metrics, results, limitations, compute)
  and *methodology* (architecture, training data, preprocessing, objective, loss,
  optimization, hyperparameters, evaluation method). "Not reported" instead of guesses.
  Each paper's cells are cached per (version, kind, model, prompt version) in
  `paper_extractions`, so a paper is read once and reused by every comparison it's in.
  Sources renumbered across papers (a cell can only cite its own paper). Overview above the
  table written from the finished table, checked with each passage's own paper title.
  Row agreement (similar / different / partial / none) from word overlap.
- **API**: `POST/GET /comparisons`, `GET/DELETE /comparisons/{id}`; same papers in any order
  return the existing comparison; `force` regenerates; stale reasons (newer version, deleted
  paper, model or prompt changed); deleted papers flagged and their sources unlinked.
  Migration `c78d9028c2be`. Job `comparison.generate` with per-paper progress.
- **UI**: **Compare** in the sidebar; library checkboxes (grid and list, with reasons for papers
  that can't be picked yet) + "Compare selected" bar; paper header **Compare**; builder
  (`/compare?papers=…&kind=…`, paper picker, Papers / Methodology); result page
  (`/compare/:id`) with overview + support badge, table with sticky category column, column
  pinning, horizontal scroll, **Highlight differences** with an honest count ("9 of 10 rows
  differ … compared by words"), citation popovers, export to Markdown / CSV / clipboard,
  sources grouped by paper, regenerate, delete, recent comparisons.

#### Verified
- Backend 233 passed (+4 opt-in skipped), ruff/format clean, mypy clean for new code.
  Frontend 72 tests, typecheck, oxlint, build. 11 comparison API/unit tests (cells only cite
  their paper, cache reuse counted in model calls, order-independent dedupe, methodology,
  2–5 limit, duplicates, other users, failure + hint, list/delete, deleted paper).
- Real model (qwen2.5:3b) in headless Chrome: library → select two papers → Compare selected →
  per-paper progress → table + overview in 110–180 s (≈1 min per new paper); highlight,
  pin + horizontal scroll, citation popover, Markdown export downloaded, stale note after a
  prompt change, regenerate, mobile + dark. No console errors.
- Found with the real model and fixed:
  - **Mobile page overflow (429 px on a 390 px screen)**: visually hidden labels inside the
    table escaped the scroll container (absolute positioning, unpositioned container) →
    container is `relative` (same fix applied to the library's list view).
  - **Empty cells**: the model answered "MODEL: [3]" with no text. **Correction to Session 4:**
    its prompt A/B counted such citation-only answers as answered. Re-measured with the
    metric fixed (13 fields × 2 runs): placeholder example 6/26 citation-only; adding an
    explicit answer template 0/26 (85% cited; uncited answers are still checked against all
    the group's passages). Template adopted for summaries, comparisons and the overview;
    citation-only fields are also asked for once more.
  - Overview citing all 18 passages at once → runs of more than 4 citations dropped (the
    sentence is checked as uncited); "is not reported in the provided passages" recognised as
    Not reported; labels repeated inside a field; "[6]. [7] Next sentence" markers moved to
    the sentence they start; duplicate trailing markers. Last three replayed on the stored
    real replies (no repeated labels left).
- Final real-model run: 18 of 29 statements directly supported; the rest shown as partly /
  not supported (mostly paraphrase embellishments by the 3B model).

#### Not yet verified / known limitations
- The last post-processing fixes (citation-dump drop, inline label removal) were replayed on
  real replies and covered by tests, not re-run end to end in the browser.
- Agreement is lexical: two unrelated papers differ in every row; related ideas in different
  words count as different (the UI says so). Semantic agreement could use the embedder later.
- Chat "Compare" mode (brief §122) not added; the research chat already handles comparison
  questions. Comparison filters by collection arrive with Phase 9.
- Walkthrough ran with `RERANKER_PROVIDER=none` and `SUMMARY_AUTO=false` to stay within RAM
  (1.2–1.8 GB free with Ollama loaded).

#### Next session: Phase 9 plan (organization)
1. Collections (CRUD, add/remove papers, collection page), tags (per paper, filter).
2. Notes in Markdown, optionally anchored to a passage (reader highlight → "Add note").
3. Bookmarks and reading status (to-read / reading / done); filters in the library, search
   and comparison picker by collection / tag.
4. BibTeX / RIS export of a collection.

### Session 4: Phase 7, 2026-10-01/02 — paper summaries ✅

#### Delivered
- **Structured summaries** (`services/summaries/`): problem, motivation, method, architecture,
  dataset, experiments, results, limitations, future work, key contribution, one-line takeaway.
  Every statement cites passages of the paper; "Not reported." instead of guesses.
- **Map-reduce over section groups**: 4 model calls (overview / method / experiments /
  outlook), each from that part of the paper (section openings first, then paper-local BM25
  on the group's topic words, token budget); whole-paper BM25 fallback for papers without
  headings. Reduce: the takeaway is written from the drafted fields.
- **Checked like chat answers**: claim-level NLI per section and overall ("8 of 14
  statements directly supported…"), invalid citations dropped, sections labelled Well /
  Partially / Not supported / Not reported.
- **Job + cache**: `paper.summarize` job with live progress ("Reading the method…"),
  sections saved as each group finishes; cached by (version, model, prompt version);
  `force` regenerates while the old summary stays visible until the new one is ready; failed
  regenerations keep the previous summary; out-of-date summaries say why.
  `SUMMARY_AUTO=true` summarizes after indexing when the model is ready (never fails the upload).
- **API**: `GET/POST /documents/{id}/summary`; table `paper_summaries` (migration `a553bc587af8`).
- **UI**: AI summary card on the Overview tab (takeaway first, collapsible sections, status
  dots that spell out problems, "Not reported" rows, overall support popover with every
  statement, Copy as Markdown with sources, View sources sheet, Regenerate); header
  **Summarize** button; citations jump the reader to the exact passage; progressive display
  while writing; model-not-ready / not-indexed reasons; mobile and dark mode.

#### Verified
- Backend 217 passed (+4 opt-in skipped), ruff + format clean, mypy clean for new code.
  Frontend 64 tests, typecheck, oxlint, build. 24 summary tests (parsing, passage selection,
  verification, API, cache, failure, auto-summary, no-headings paper, loop guard, retry).
- Real model (Ollama qwen2.5:3b, CPU) in headless Chrome: upload → automatic summary in
  ~95–115 s → sections appear group by group → citations open the reader → stale note after a
  prompt change → Regenerate (previous summary dimmed until replaced) → mobile/dark, no
  horizontal overflow, no console errors.
- Found with the real model and fixed (each measured):
  - The title/author block as a passage made the model answer "PROBLEM: [2]" with no text →
    excluded (and fields that are only citations count as not reported).
  - The NLI checker couldn't link "we learn an update…" to the paper → title before every
    window: 0.00 → 0.82. Bare lists ("MedQA, CaseHOLD, …") → checked as "The datasets used
    are …": 0.00 → 0.81–0.95.
  - Citation loops ("[7] [9] [6] [7] …" to the token limit, ~40 s) → generation stops on a
    run of 8 markers; adjacent markers merged; bare captions no longer given as passages.
  - **The prompt's example sentence leaked into output** ("Adapters cut GPU memory by 60
    percent" — taken from a sample paper). A/B on real passages (2 runs × 4 groups): fact
    example 100% cited, placeholder 100% cited, meta sentence 68% → placeholder. The same
    example was in the **chat prompt**, fixed there too (`rag-v3`).
  - "[6] Adapters cut …" without a full stop is now a sentence boundary (chat too).
  - Marker-first fields, "Researchers should remember that …" framing, "[CONTRIBUTION]"
    used as a citation, skipped fields (asked for once more).
- Final real-model run: 8 of 14 statements directly supported; the unsupported ones were real
  overstatements by the 3B model ("matched full fine-tuning" vs "within one point") or
  embellishments in motivation / contribution — shown as such, not hidden.

#### Not yet verified / known limitations
- The last fixes (placeholder example, skipped-field retry, label markers) were measured with
  the prompt A/B script and covered by tests, but not re-run through the browser: the API
  server was stopped for low memory and wasn't restarted.
- The 3B model still embellishes (motivation/contribution often "not supported"); larger
  models via the OpenAI-compatible provider are supported but untested live.
- ~1.5–2 min per summary on this CPU; auto-summaries queue behind each other in Ollama.
- One unexplained frontend test failure in a single run right after the backend suite;
  7 consecutive clean runs since (suspected timing flake under load).
- Summaries of a single paper only; multi-paper summaries belong to literature review (Phase 11).

#### Next session: Phase 8 plan (comparison)
1. Compare 2–5 papers: structured extraction per paper (task, method, data, metrics,
   results, limitations) reusing the summary fields where cached; "Not reported" cells.
2. Methodology comparison view; every cell cited to its passage; verification per cell.
3. Export the table (Markdown / CSV); header "Compare" button and a library multi-select.

### Session 2 (continued): Phase 5, 2026-10-01

**Goal:** a second, more precise stage on top of retrieval: rescore the fused candidates with a
cross-encoder, without making search feel slow.

#### Done
**Backend: `app/services/reranking/`**
- [x] `RerankerProvider` interface (scores in [0, 1]); local `CrossEncoder` (model manager,
      CUDA/MPS/CPU, fp16 on CUDA, batching, logits → sigmoid), any Jina/Cohere-style `/rerank`
      API (retries, user-safe errors, refused in `LOCAL_ONLY`), deterministic lexical reranker
      for tests; selected by `RERANKER_PROVIDER` / `RERANKER_MODEL`
- [x] **Model choice measured, not assumed**: on this CPU, reranking 30 passages took 0.79 s with
      `cross-encoder/ms-marco-MiniLM-L-6-v2` vs 6.6 s with `BAAI/bge-reranker-base` (same top 3),
      so MiniLM is the default and BGE is documented as the GPU option
- [x] Search pipeline: retrieve (50/retriever) → RRF → rerank the top `RERANK_CANDIDATES` (30)
      → return; every result keeps its fused rank; `rerank` / `rerank_candidates` per request
- [x] Per-(model, query, passage) score cache: repeated or refined searches only score new pairs
- [x] Failure-safe: reranker errors → fused order + warning; explicit `rerank=true` with no
      reranker → warning
- [x] Latency recorded per stage (`rerank` timing, `rerank_latency_ms` metric, cache-hit counter);
      reranker warmed at startup; `/api/v1/ai/status` reports reranker and retrieval settings
- [x] 11 new backend tests (148 total) + opt-in real cross-encoder test

**Frontend**
- [x] **Progressive results**: fused results appear immediately, "Refining the order…", then the
      reranked order swaps in with a "Reranked" badge (model on hover)
- [x] Advanced: "Rerank results" toggle (with the brief's tooltip text), `?rerank=0` in the URL
- [x] Trace panel: "Reranked" tab with relevance and movement vs. fused rank (▲2 / ▼2 / =);
      reranker model and candidate count in the parameters; rerank timing
- [x] Result tooltip shows "Before reranking: #N"; Settings → AI shows the real reranker
- [x] 2 new tests (43 total)

#### Verified manually
Real servers + headless Chrome with BGE-small + MiniLM cross-encoder on CPU. For "which method keeps
latency low while improving recall": fused results came back about 1 s after typing (debounce included) with "Refining the
order…", then the reranked order at about 1.9 s. Fused ranking put a LoRA "Background" passage first
(it matches "low" and "latency"); the reranker moved the abstract that answers the question to #1 (▲2).
Repeating the search reranked in 55 ms (cache). Turning reranking off works; no console errors.

#### Not yet verified / known limitations
- GPU path (fp16 cross-encoder) untested: no GPU here.
- API reranker tested against a mock of the Jina/Cohere response shape, not a live service.
- "Reranking improvement" as a metric (nDCG before/after) belongs to the evaluation framework (Phase 12).
- `MAX_LOADED_MODELS=2` fits embedder + reranker; a local LLM in Phase 6 will need the LRU
  unloading (already implemented) or a higher limit.

#### Next session: Phase 6 plan
1. `LLMProvider` interface: Ollama, OpenAI-compatible, local HF; streaming; token
   counting; configurable models; `LOCAL_ONLY` enforcement.
2. Query processing: intent (factual/method/comparison/…), entities, filters and temporal
   constraints from the question; only rewrite when it helps; optional expansion (HyDE later).
3. Context selection: rerank top-K, score threshold, near-duplicate removal, MMR, neighbour
   stitching, token-budget packing with numbered evidence blocks.
4. Generation with mandatory `[n]` citations; citation validation (unknown indices stripped);
   claim-level verification (supported / partial / unsupported) and an "insufficient evidence"
   answer when retrieval is weak.
5. Conversations + messages tables with retrieval trace and generation config; SSE streaming API.
6. UI: Research Chat (global) and paper chat, streaming answer, citation chips that open the reader
   at the cited passage (deep links + boxes are ready), evidence panel, support indicators,
   split view reader + assistant.

### Session 2 (continued): Phase 4, 2026-10-01

**Goal:** find passages across the whole library by exact words, by meaning, or both, and
show how each result was found.

#### Done
**Backend: retrieval (`app/services/retrieval/`)**
- [x] One analyzer for indexing, queries and highlights: NFKC + casefold, stopwords, Snowball
      stemming, hyphen splitting, numbers kept, exact character offsets even through PDF
      ligatures ("ﬁ" → "fi")
- [x] **Hand-written Okapi BM25** (Lucene IDF, `BM25_K1`/`BM25_B`), inverted index with
      incremental add/remove, filtering *before* the top-k cut, deterministic ties; verified
      against hand-computed scores
- [x] Per-user BM25 libraries kept in sync by diffing the user's current indexed versions on
      each search (one query; only changed versions are tokenized), so it's correct across API
      processes and Celery workers without invalidation messages; LRU-bounded memory
- [x] PostgreSQL full-text retriever (`SPARSE_RETRIEVER=postgres`): GIN expression index migration,
      `ts_rank_cd`, OR semantics, same filters; tested in CI against real PostgreSQL
- [x] Dense retriever: cached query embeddings, Qdrant ANN limited to the user's *current*
      versions embedded with the active model (old versions never leak into results)
- [x] **Reciprocal Rank Fusion** (`RRF_K`) behind a `FusionMethod` interface, keeping each
      retriever's rank, score and contribution per hit
- [x] Filters (year range, authors, document type, chosen papers, sections) resolved in SQL and
      applied inside every retriever; reference lists excluded unless asked for
- [x] Results: passages with paper info, section, pages, boxes, matched-term highlights and the
      best snippet window; `debug=true` returns the full trace (BM25 list with matched terms,
      dense list, fused list with RRF contributions, parameters, per-stage timings)
- [x] Graceful degradation: embedder down → hybrid falls back to keyword with a warning;
      semantic-only → 503 with a hint. Warning when papers were indexed with another model
- [x] `POST /api/v1/search`, `GET /api/v1/search/facets` (years, authors, types, sections and
      suggested searches taken from the library's own keywords)
- [x] Embedding model warmed in the background at startup (first search no longer waits ~10 s)
- [x] 29 new backend tests (137 total) + PostgreSQL FTS test (`TEST_POSTGRES_URL`, runs in CI)

**Frontend: Search page**
- [x] Large search box ("Search your research…"), search-as-you-type (debounced) and Enter,
      `/` to focus, suggested searches from the library, everything in the URL (shareable)
- [x] Results grouped by paper: title, authors, year, venue, type; best passage with section,
      page, highlighted terms, relevance bar (relative to the best match, no fake "confidence"),
      "Matches your words / the meaning / both" with per-retriever ranks on hover,
      "Show full passage", "N more matching passages", "Open in paper" (opens the reader on the
      exact passage)
- [x] Filters: sidebar on desktop, drawer on mobile/tablet (year range, document type, author,
      section, include reference lists, clear)
- [x] Advanced (hidden by default): Hybrid / Keyword / Semantic, result count, and the
      "How these results were found" panel (BM25 / Dense / Fused tabs, scores, matched terms,
      RRF contributions, stemmed query terms, timings, parameters)
- [x] Empty library, still indexing, no results (with the right next step), error and warning states
- [x] ⌘K palette: "Search passages for …" as the first action
- [x] 16 new tests (41 total)

#### Verified manually
Real servers + headless Chrome with BGE-small on CPU: empty state → upload 3 files → suggestions
→ live search (first results ~0.86 s after typing including the 300 ms debounce; warm hybrid
searches 10–20 ms server-side) → expand passages → author filter → Advanced trace (BM25 matched terms,
RRF contributions) → keyword-only no-results state → "Open in paper" lands on and highlights the
passage → ⌘K → mobile drawer → dark mode. No console errors.
Bugs found and fixed:
1. **Concurrent uploads sometimes weren't indexed** (Phase 3 bug): embedded Qdrant persists through
   one SQLite connection and isn't thread-safe, so parallel indexing jobs corrupted its transactions
   ("cannot commit - no transaction is active"). All embedded-mode calls are now serialized;
   regression tests hammer the store from 8 threads and upload 9 papers concurrently.
2. **Deep links scrolled but never highlighted** (Phase 2 bug): the reader treated the target it was
   mounted with as already seen. Fixed and covered by a test; matters for citations in Phase 6.
3. "Open in paper" for captions/tables highlighted nothing, since deep links resolve by paragraph.
   In-app links now pass the passage's exact boxes.
4. Buttons inside the search form defaulted to `type=submit`; choosing a mode was immediately
   overwritten by the implicit form submit.
5. The trace reported returned candidates as the configured candidate limit.
6. Local setup: the editable install was stale (`app` resolved as a namespace package outside
   `backend/`, so the Windows DLL fix in `app/__init__.py` never ran and torch failed to load in
   scripts). Reinstalled; no code change.

#### Not yet verified / known limitations
- PostgreSQL FTS retriever runs only in CI (no PostgreSQL locally); the generated SQL was
  checked against the index expression.
- Filters for collections, topics, datasets, models and methods arrive with Phases 9–10.
- Porter-style stemming over-conflates sometimes ("computed" ~ "computer"); the trace shows the
  stemmed terms so it's visible.
- Embedded Qdrant allows one process: scripts can't run semantic search while the dev server
  is running (use `QDRANT_URL` for multi-process setups; Docker does).
- Main JS bundle is 631 kB; code-splitting is scheduled for Phase 15.

#### Next session: Phase 5 plan
1. `RerankerProvider` interface: local cross-encoder (`BAAI/bge-reranker-base`, model manager,
   batching, fp16 on CUDA) + API rerankers (Cohere/Jina-compatible, blocked in `LOCAL_ONLY`).
2. Rerank the fused top-N (`RERANK_CANDIDATES`) down to `RERANK_TOP_K`; cache by (query, passage
   set, model); graceful fallback to fused order if the reranker fails.
3. Per-stage latency (retrieve / fuse / rerank) in the trace and metrics; reranker scores and
   rank changes in the "How these results were found" panel.
4. Search UI: "Rerank results" in Advanced (on by default when a reranker is available),
   rank-movement indicators in the trace.
5. Tests: ordering with a fake reranker, fallback, caching, latency accounting; opt-in real
   cross-encoder test.

### Session 2: Phase 3, 2026-10-01

**Goal:** every paper split into citable passages, embedded locally, and stored in a vector index.

Most of the Phase 3 code was written at the end of the previous session but not committed or
logged. This session reviewed it, finished the phase gate (verification, fixes, tests, docs) and committed.

#### Done
**Backend: chunking (`app/services/chunking/`)**
- [x] 5 strategies behind one `Chunker`: fixed-token, recursive, sentence, **section-aware**
      (default), semantic (splits where adjacent-sentence embedding similarity drops)
- [x] Tables, equations, captions and code are atomic chunks; sizes are counted in the embedding
      model's own tokenizer (fallback counter when it isn't installed)
- [x] Every chunk is the exact slice `full_text[char_start:char_end]` with page span, section,
      paragraph index and PDF boxes, so it can be cited and highlighted
- [x] Contextual chunk headers ("Paper › Section › Subsection") embedded with each passage (toggle)

**Backend: embeddings, model manager, vector store**
- [x] `EmbeddingProvider` protocol + providers: sentence-transformers (BGE/E5 query/passage
      prefixes applied automatically), OpenAI-compatible API (blocked when `LOCAL_ONLY`),
      dependency-free hashing provider (tests)
- [x] Model manager: CUDA → MPS → CPU detection, float16 on CUDA, lazy load, LRU capacity and
      idle unloading, CUDA cache release, thread-safe; status exposed at `/api/v1/ai/status`
- [x] `embedding_cache` keyed by `(model, sha256(text))`: reprocessing, new versions and
      duplicate uploads never re-embed identical text
- [x] Qdrant wrapper: embedded local mode or server (`QDRANT_URL`), one collection per
      model+dimension (vectors from different models never mix), payload filters (user,
      document, version, section kind, year; indexed in server mode), idempotent upserts,
      deletes on document delete
- [x] Indexing as stages of `document.process` (chunking → embedding → indexing) with progress
      ("Embedding passages (64 of 120)"); a separate `document.index` job for retries/merges
- [x] **Indexing failure keeps the paper readable**: it's flagged "Not searchable" with the reason
      and a retry, instead of failing the upload
- [x] Similar papers v1: nearest neighbours of a paper-level vector (title + abstract + keywords),
      with *checkable* reasons (shared keywords/authors/venue/area, IDF-ranked shared terms)
- [x] API: `POST /documents/{id}/reindex`, `GET /documents/{id}/chunks`, `GET /documents/{id}/similar`
- [x] `python -m app.cli reindex --pending|--all [--user]` for model or chunking changes
- [x] Migration (chunks, embedding_cache, index columns) + a migration test that upgrades over
      existing document/version rows
- [x] 30 new backend tests (108 total) + an opt-in real-model test (`RUN_MODEL_TESTS=1`)

**Frontend**
- [x] Overview: "Search index" card (Searchable / Indexing… / Not searchable + retry / Index now)
- [x] "Similar papers" tab with scores, reasons and empty states
- [x] "Passages" tab (behind Settings → Advanced → Show technical details): every chunk with kind,
      section, page, token count, expandable text with its context header, "Show in paper"
- [x] Settings → AI shows the real embedding model, device, chunking strategy and vector store
- [x] Processing panel shows the "Indexing for search" step
- [x] 4 new tests (25 total)

**Infra & docs**
- [x] Docker image now installs PyTorch (CPU by default; `TORCH_INDEX` build arg for CUDA) and
      sentence-transformers. Model cache is on a volume, backend waits for Qdrant, and the
      embedding/chunking env vars pass through
- [x] `.env.example`, DEVELOPMENT.md (models, reindexing, GPU), ARCHITECTURE.md (schema as built), README

#### Verified manually
Real servers + headless Chrome with the real `BAAI/bge-small-en-v1.5` on CPU: uploaded 2 PDFs and a
Markdown file → processed and indexed in ~10 s → Search index card → Similar papers (the Markdown copy
of the same paper ranks first at 1.00, an unrelated paper gets 0.74 with an honest "same venue" reason)
→ Passages tab → "Show in paper" highlights the passage → mobile layout. `reindex --all` on 9 papers:
0 re-embedded, everything came from the cache. The Qdrant folder was deleted and rebuilt from the cache alone.
Bugs found and fixed:
1. "Show in paper" (passages, and also figures/tables/equations from Phase 2) didn't scroll when the
   target was below the fold: the reader tab was still `display:none` when the scroll ran.
   It now retries until the reader is visible.
2. A test used `monkeypatch.undo()`, which also reverted conftest's settings patch, so the retry ran
   with the real `.env` (downloaded BGE, and wrote test vectors into the **dev** Qdrant folder, failing
   when the dev server held its lock). The patch is now scoped, and the suite runs in 28 s instead of 80 s.
3. The Docker image had no PyTorch/sentence-transformers, so every paper would have been
   "Not searchable" under Docker.

#### Not yet verified / known limitations
- Docker/PostgreSQL/Qdrant-server path still only verified by CI (no Docker on this machine);
  the larger image (CPU torch) hasn't been built locally.
- No GPU on this machine: the CUDA/MPS detection and float16 paths are untested.
- Embedded Qdrant allows one process per folder. With `JOB_BACKEND=celery` you must use
  Qdrant server (`QDRANT_URL`), which docker-compose already does.
- Semantic chunking calls the embedder per sentence, so it is slower; section-aware stays the default.
- Similar papers needs ≥ 2 indexed papers; scores between near-duplicates are ~1.0 by design.

#### Next session: Phase 4 plan
1. Own BM25 implementation (k1/b configurable, tokenization with stemming/stopwords, per-user
   inverted index persisted and updated incrementally on index/delete) + PostgreSQL FTS backend.
2. Dense retrieval over Qdrant with payload filters (document, year, section kind, doc type).
3. Reciprocal Rank Fusion (configurable k) with per-retriever ranks kept for explanation.
4. Search API: query → hybrid results with highlights, filters, pagination, latency per stage.
5. Search page: simple box + advanced filters, result cards (paper, section, page, snippet with
   highlighted terms, "open in reader"), "why this result" panel (BM25 score/rank, dense
   score/rank, RRF contribution), empty/no-results/error states, ⌘K integration.
6. Tests: BM25 math against hand-computed values, RRF properties, filter isolation between users.

### Session 1 (continued): Phase 2, 2026-09-30

**Goal:** documents in, structured and described, readable in the app.

#### Done
**Backend: ingestion pipeline (`app/services/ingestion/`)**
- [x] `ParserProvider` registry: PDF (PyMuPDF), DOCX, HTML, Markdown, TXT; new formats plug in
- [x] Layout-aware PDF parsing: text-layer detection, OCR fallback provider (Tesseract; clear
      message when unavailable), style-aware block splitting, two-column reading order,
      running header/footer and page-number removal, arXiv margin stamp capture,
      ruled + booktabs table detection, figure detection (images/vector drawings),
      equation detection (math fonts/symbol density, verbatim text), PDF outline support
- [x] Structure analysis: headings from outline / numbering / canonical names / font
      statistics; relative levels for markup formats; section tree with canonical kinds
      (inherited by subsections); paragraphs merged across column/page breaks; every
      paragraph keeps page span, char offsets into `full_text` and PDF bounding boxes
- [x] Captions linked to figures/tables (bbox proximity + unambiguous fallback), figure
      context (paragraphs mentioning "Figure N"), equation context, parsed references
      (title, year, DOI, arXiv)
- [x] Deterministic metadata with provenance per field: title, authors (+emails,
      affiliations), abstract, DOI, arXiv ID, year/date, venue, keywords, research area
- [x] Upload validation: extension allow-list, magic bytes (a fake `.pdf` is rejected),
      streaming size limit, filename sanitization; SHA-256; storage behind `FileStorage`
- [x] Versioning (upload new version); duplicates: exact (hash), probable (DOI/arXiv/title),
      possible (title similarity); the user resolves: keep both / merge as version / delete.
      The newer upload is flagged regardless of which finishes processing first
- [x] `document.process` job: staged progress with readable detail ("Extracting page
      12 of 38"), parser runs in a thread, idempotent reprocessing, user corrections
      protected, thumbnail rendering, reproducibility record (pipeline version, parser, stats, timings)
- [x] Signed asset URLs (thumbnail, page PNGs, original file; HTML never served inline)
- [x] Documents API: upload (multi, partial failure), list (search/sort/status), stats,
      detail, status, structure, metadata PATCH, reprocess, versions, duplicate resolution, delete
- [x] Migration with correct circular-FK handling (verified up/down/up on SQLite)
- [x] 42 new tests (78 total): parsers per format, structure, anchors, tables/figures/
      equations/references, metadata, validation, dedupe, full API flows, privacy

**Frontend**
- [x] Upload manager (3 concurrent, per-file progress, browser prechecks, continues in the
      background), upload dialog, drag-and-drop anywhere on Papers, Ctrl/Cmd+U
- [x] Papers library: grid (thumbnails) / list, filter, status chips, sort, live progress,
      status popovers (stage, ETA, retry), duplicate badges, empty and no-results states
- [x] Paper page: header + actions, duplicate resolution banner, processing/failed states,
      tabs: Overview (abstract, keywords, metadata with provenance dots, OCR/warnings, file
      and versions), Paper (reader), Figures (cropped from the page), Tables, Equations, References
- [x] Reader: lazy page images, TOC, zoom, page navigation, in-paper search with highlight
      overlays; structured text reader for non-PDF; deep links `?tab=paper&page=&char=`
      (ready for citations)
- [x] Metadata editor (only changed fields are saved, and they're protected from reprocessing)
- [x] Dashboard with real stats, continue reading, recent papers; ⌘K paper search + upload action
- [x] 9 new tests (21 total)

#### Verified manually
Real servers + headless Chrome: uploaded 5 files (2 PDFs, DOCX, Markdown, scanned PDF) via
Ctrl+U → live progress → 4 ready, the scanned PDF failed with the OCR explanation → paper page,
reader with search highlight, figure crop, table, equation, references, duplicate banner,
dark-mode dashboard, mobile library. Bugs found and fixed:
1. Heading detection misread "Introduction" (the roman-numeral strip ate the "I").
2. Right-column headings near the gutter were treated as full-width, giving the wrong section order.
3. Venue "Science" matched from "Department of Computer Science"; venues now need a year.
4. DOCX year came from the Word template's creation date.
5. Bar-chart rectangles were detected as a table; a caption and its table split across columns didn't link.
6. Naive SQLite datetimes showed as "6 hours ago"; the API now always emits UTC.
7. The duplicate flag landed on the older upload when processing finished out of order.
8. Async lazy-load crash on `document.current_version`; the relationship is now `lazy="raise"`.
9. Grid cards didn't fill their cells; invalid `<p><div>` nesting on the dashboard.

#### Not yet verified / known limitations
- OCR is untested end-to-end here (Tesseract isn't installed locally); it's in the Docker image.
- The Docker/PostgreSQL path is still only verified by CI (Docker isn't installed on this machine).
- Heuristic parsing is tuned on synthetic papers; real-world PDFs (math-heavy, unusual
  layouts) will need iteration. The parser interface allows swapping in GROBID/Marker later.
- Entity fields (datasets, models, metrics, tasks) are deferred to Phase 10 as planned.

#### Next session: Phase 3 plan
1. `chunks` + `embedding_records` tables; chunking strategies (fixed-token, recursive,
   sentence, section-aware default, semantic) with tables/equations/captions kept atomic.
2. Tokenizer-aware sizes; contextual chunk headers ("Paper › Section") as an option.
3. `EmbeddingProvider` (sentence-transformers BGE/E5 with query/passage prefixes), model
   manager (CUDA detection, lazy load, idle unload, dtype), content-hash cache.
4. Qdrant: embedded local mode + server mode, payload indexes (user, document, section kind,
   year), idempotent upserts, deletion when documents are deleted.
5. Extend `document.process` with chunking → embedding → indexing stages.
6. "Similar papers" v1 (document embeddings) on the paper page.
7. UI: a chunk inspector in an "Advanced" panel on the paper page.

### Session 1: 2026-09-30

**Goal:** analyze the brief, design the architecture, and build Phase 1.

#### Done

**Planning & design**
- [x] Architecture, services, provider abstraction, full DB schema, API design, RAG pipeline,
      bottlenecks and risks → `docs/ARCHITECTURE.md`
- [x] 15-phase roadmap plus 13 suggested additions (arXiv/DOI import, BibTeX export,
      highlight-to-ask, answer feedback → eval set, contextual chunk headers, …) → `docs/ROADMAP.md`

**Backend (`backend/`)**
- [x] FastAPI app factory, pydantic-settings config (env/.env; production guard on `JWT_SECRET`)
- [x] Async SQLAlchemy 2 + Alembic; portable types (SQLite locally, PostgreSQL in Docker)
- [x] Tables: `users`, `refresh_tokens`, `jobs`, `audit_logs` (initial migration)
- [x] Auth: register / login / refresh / logout / change-password
  - Argon2id hashing; 30-min JWT access tokens
  - Rotating opaque refresh tokens in httpOnly SameSite=Strict cookie (hashed at rest)
  - Refresh-token reuse detection revokes all sessions
  - Account-enumeration and timing protection
- [x] Account: profile, preferences (merged, validated), sessions list/revoke, account deletion
- [x] Background job system: registry + runner + dispatchers (inline asyncio / Celery),
      dispatch-after-commit, progress reporting, user-safe errors, retry
- [x] Rate limiting (Redis or in-memory), request-ID middleware, structured logging with
      secret redaction, security headers, consistent error JSON
- [x] `/health`, `/ready` (DB + Redis probes), `/metrics` (Prometheus format), `/api/v1/config`
- [x] **36 tests passing** (auth flows, cookie flow, token rotation/reuse, isolation, jobs,
      rate limiting, metrics, config parsing); ruff lint + format clean

**Frontend (`frontend/`)**
- [x] Vite + React 19 + TS + Tailwind v4; design tokens (semantic colors, light/dark,
      WCAG-AA pairs), typography scale, reduced-motion support
- [x] Design-system components: Button, Input/Field, Card, Badge, Dialog, Tooltip, Skeleton,
      ProgressBar, EmptyState, ErrorState, Kbd, PageHeader, Logo, Toaster
- [x] App shell: collapsible sidebar with tooltips, mobile/tablet drawer, top bar,
      user menu with theme switcher, ⌘K/Ctrl+K command palette, `/` shortcut, skip link
- [x] Pages: Login, Register (field-level errors), Home dashboard (hero, CTAs, empty
      library state, live processing-jobs widget), Settings (profile, password, sessions,
      appearance, AI config, delete account), Help (keyboard shortcuts), 404, and honest
      "Coming soon" pages for unbuilt sections
- [x] Onboarding dialog (Skip / Get started, remembered per account)
- [x] Typed API client: in-memory access token, single-flight refresh + retry, friendly errors
- [x] Preferences (theme, text size, sidebar) persisted locally and synced to the account
- [x] **12 tests passing** (vitest); oxlint clean; typecheck clean; production build OK

**Infra & docs**
- [x] `docker-compose.yml` (postgres, redis, qdrant, backend, celery worker, nginx frontend),
      Dockerfiles, nginx SPA + API proxy config (SSE-ready), `.dockerignore`
- [x] GitHub Actions CI: backend lint/tests + migrations on real PostgreSQL, frontend
      lint/typecheck/test/build, Docker build
- [x] `.env.example`, `.gitignore`, `scripts/dev.ps1`, `scripts/dev.sh`
- [x] README (with Mermaid diagrams), DEVELOPMENT.md, SECURITY.md

#### Verified manually
- Ran real uvicorn + Vite servers; drove the UI in headless Chrome: register (validation
  error → success) → onboarding → dashboard → ⌘K palette → settings → dark mode →
  reload (session restored from cookie, theme persisted) → mobile layout + drawer.
- Bugs found and fixed during verification:
  1. Security writes (session revocation on token reuse, failed-login audit) were rolled
     back when the request errored → now committed before raising.
  2. `tailwind-merge` was dropping text colors next to custom type-scale classes
     (dark text on primary buttons) → configured merge groups + regression test.
  3. Comma-separated `CORS_ORIGINS` crashed settings loading (would have broken
     Docker startup) → fixed + regression tests.

#### Not yet verified / known limitations
- **Docker is not installed on this machine**, so `docker compose up` and the PostgreSQL
  migration path haven't been run locally. CI covers both on push.
- Not a git remote yet. The repo was initialized locally and committed; push to GitHub
  to activate CI.
- The JS bundle is ~517 KB minified (single chunk); route-level code splitting is planned
  for Phase 15.

#### Next session: Phase 2 plan
1. Models + migration: `documents`, `document_versions`, `document_metadata`, `pages`, `sections`.
2. Upload API: multi-file, size limit, extension + magic-byte MIME validation, filename
   sanitization, SHA-256 → exact-duplicate / new-version detection.
3. `ParserProvider` interface + PDF (PyMuPDF: text layer detection, blocks, fonts,
   columns, headings, captions, references), DOCX, HTML, Markdown, TXT parsers.
4. OCR fallback provider (Tesseract via `pytesseract`, optional) with the "OCR used" flag.
5. Metadata extraction (title/authors/abstract/DOI/arXiv/year) + manual correction API.
6. `document.process` job with per-stage progress.
7. UI: Papers library (grid/list, sort, status badges, drag-and-drop upload zone,
   progress, retry, error details), paper page v1 (header, metadata edit, section tree,
   basic reader).
8. Synthetic sample papers for tests (no copyrighted PDFs).

### Session 3: Phase 6, 2026-10-01 — RAG research chat ✅

#### Delivered
- **LLM providers** (`services/llm/`): Ollama (NDJSON streaming; "not installed → ollama pull"
  and "can't reach Ollama" errors with the fix), OpenAI-compatible (SSE; vLLM, LM Studio,
  OpenAI), deterministic extractive
  model for tests. `LOCAL_ONLY` refuses remote ones. `GET /ai/status` reports readiness.
- **RAG pipeline** (`services/rag/`): rule-based query understanding (intent, entities,
  year filters, follow-ups, "about this paper"), context selection (relevance floor, near-dup
  removal, MMR, token budget, every decision traced), numbered evidence prompt, citation
  validation (invented `[n]` removed and reported), claim-level NLI verification → Well
  supported / Partially supported / Insufficient evidence with a plain explanation. No evidence
  → the fixed "insufficient evidence" answer without calling the model.
- **Persistence + API**: conversations, messages (retrieval trace, generation config, tokens,
  latency, support), citations (chunk, page, boxes, quote, score, cited, support status).
  SSE stream of stage / query / evidence / token / answer / verification / done / error; a
  stopped or failed answer is saved with its status.
- **UI**: Research Chat (`/chat`), conversation list (rename / delete), streaming answer with a
  stage indicator and Stop, safe Markdown subset (lists, tables, code; no HTML injection),
  `[n]` chips → source card (title, page, section, passage, relevance, Open paper with exact
  highlight), "View sources" evidence panel with "How this answer was found", support badge
  with per-claim checks, copy with sources, model-not-ready banner. **Paper split view**: Chat
  button on a paper, reader left / assistant right, citations move the reader; a sheet on
  mobile. Heavy routes are lazy-loaded (main bundle 673 → 355 kB).

#### Verified
- Backend 187 passed + opt-in real-model tests (embedder, MiniLM reranker, NLI verifier): 190.
  Frontend 55 tests, typecheck, oxlint, build.
- Headless Chrome walkthrough, desktop / mobile / dark: Ollama missing → clear error and banner;
  off-topic question → "insufficient evidence" without the model; streamed answers with
  citations, source card, support popover, sources panel, open-in-paper highlight, follow-up
  question, split view (citation → reader page). No console errors.
- Found in the walkthrough and fixed:
  - The first answer took 57 s while the NLI model loaded → now warmed at startup (0.4 s after).
  - Paper chat: "How does the proposed method work?" scored ≤ 0.002 for every passage with the
    MS MARCO reranker, so nothing was used. Appending the paper title fixed that but also gave
    an off-topic question 0.89 (rejected). Now: in a single paper's chat, questions about the
    paper itself fall back to BM25 + dense order; off-topic ones are still refused.
  - Raw exception text in the Ollama hint → actionable text.

#### Real-model run (Ollama qwen2.5:3b, installed with winget along with the VC++ runtime)
- Answers stream end to end: ~18–34 s to the first text on this CPU (prompt of ~2.5k tokens),
  ~20–40 s total; citations, sources, support status and the split view all work. No console
  errors.
- Found and fixed with real answers:
  - The model sometimes writes "[3] Claim." (marker first) → the claim splitter attached
    citations to the wrong sentence. Now detected; the prompt (rag-v2) also asks for markers
    at the end with an example.
  - The verifier truncated long passages (evidence at the end scored 0.06) → 60-word windows,
    best window wins (0.99). Window size chosen by measurement (120 → 60 words).
  - "…threefold: First, …" was checked as one compound claim (0.40) → split at enumerations.
  - Uncited or wrongly cited claims are now checked against all passages and reported as
    "supported by [n], but not cited" / "…not by the passage it cites" (the model cited a
    figure caption for a number that was in the abstract).
  - Paper chat race: opening the panel switched the conversation after it opened, and URL
    updates commit in a transition, so a question sent right after "New chat" went to the
    previous conversation and was cancelled ("Stopped."). The panel now resolves the
    conversation before opening, and the selected conversation updates immediately on user
    actions (regression test added; 4/4 repeated browser runs clean).
- A pronoun hypothesis ("they" vs the paper's "we") was tested and rejected (0.96 either way),
  so no pronoun rewriting was added.

#### Not yet verified / known limitations
- The 3B model is conservative on cross-paper comparisons ("insufficient evidence" when only
  one paper covers the point) and sometimes cites captions; larger models via
  the OpenAI-compatible provider are supported but untested live (no keys here).
- CPU latency is dominated by prompt evaluation (~2.5k context tokens); `CONTEXT_TOKEN_BUDGET`
  trades answer grounding for speed.
- Deferred from the Phase 6 roadmap line: query expansion (HyDE) — measure first in Phase 12;
  local Hugging Face LLM provider — Ollama covers local models on this hardware.
- Notes added during retrieval (year filter not applied, ranking fallback) reach the saved trace,
  not the live `query` event; the Sources panel shows them after the answer is saved.
- Equations in answers are shown as LaTeX source (no typesetting yet).
- The OpenAI-compatible provider is tested against mocks, not live APIs (no keys here).

#### Next session: Phase 7 plan (paper summaries)
1. Structured summary schema: problem, method, data, results, limitations, takeaway, each with
   citations to passages; "Not reported" instead of guesses.
2. Map-reduce over sections (fits a 3B model's context), cached by (version, model, prompt
   version); regenerate on demand; job-based with progress.
3. Verify each summary statement with the NLI verifier; show support per section.
4. UI: Summary on the paper Overview tab and the header "Summarize" button; citations open
   the reader (split view).

