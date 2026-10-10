# Observability, caching and cost

What the system measures about itself, what it caches and why each cache is safe, and how
to watch it with Prometheus and Grafana.

## Language-model usage and cost

Every model call goes through `MeteredLLM` (`services/usage.py`), which wraps whatever
`get_llm` returns. When a call's stream ends — completed, failed or stopped early — it records:

| Field | Notes |
|---|---|
| user, feature, job | from `usage_scope(...)`: the job runner sets it from the job kind (`paper.summarize` → summary, `report.generate` → report, …); chat passes its own |
| provider, model | the model the provider reports, else the configured one |
| input / output tokens | from the provider; when it reports none (stopped early, failed) they are estimated from the text (~4 characters per token) and the row is marked `estimated` |
| latency, first-token time | wall time of the call, and time until the first text arrived |
| cost | priced when the call is made and stored — changing prices later doesn't rewrite history |
| status | ok / error / stopped |

Rows go to `llm_usage`; the same numbers go to the process metrics. A failure to record
is logged and never breaks an answer.

**Pricing** — USD per million tokens. Per model, overriding the default:

```bash
LLM_PRICES='{"gpt-4.1": [2, 8], "gpt-4.1-mini": [0.4, 1.6]}'
LLM_PRICE_INPUT_PER_MILLION=0      # default for any other model (local models cost nothing)
LLM_PRICE_OUTPUT_PER_MILLION=0
```

**Usage page** (`/usage`): totals, model calls per day, and a table per feature and per model
(calls, tokens, cost, latency p50/p95, first-token p50). `GET /api/v1/usage?days=30` returns
the same data, only for the signed-in user.

What it showed on the walkthrough (qwen2.5:3b, CPU): a chat call took 59 s at p50, of which
**56 s was the time to the first token** — reading the ~2,900-token prompt, not writing the
answer (~100 tokens). On this hardware the context budget, not the answer length, decides
chat speed.

## Latency per stage

`GET /api/v1/usage/performance` (shown under *Performance* on the usage page) summarizes the
process's latency histograms — search, reranking, model calls, chat answers, summaries,
comparisons, API requests — with count, mean and p50 / p95. Percentiles are estimated from
the histogram buckets by linear interpolation (as Prometheus' `histogram_quantile` does), so
they are as precise as the bucket bounds; buckets go up to 5 minutes because CPU model calls
take tens of seconds. These are process-wide aggregates, the same for every user.

## Caches

| What | Where | Why it is safe |
|---|---|---|
| Passage embeddings | `embedding_cache` table, keyed by (model, exact text) | pure function of its key |
| Query embeddings | two-tier cache `query_embeddings` | pure function of (model, query) |
| Reranker scores | two-tier cache `rerank_scores`, keyed by (model, query, passage text) | pure function of its key |
| Summaries, comparisons | their tables, keyed by paper version + model + prompt version | a changed paper or prompt gets a new key |
| Chat answers | semantic answer cache (below) | guarded; labelled; can be bypassed |

**Two-tier cache** (`core/cache.py`): a bounded LRU in each process, plus Redis when
`REDIS_URL` is set — shared by the API and the workers and kept across restarts. A local miss
checks Redis and fills the local tier. Entries are pure functions of their keys, so they never
go stale; a TTL (7 days) only bounds Redis memory. If Redis fails, the error is logged once
and the process continues with its local tier — a cache must never fail a search.
`CACHE_ENABLED=false` turns caching off (for benchmarks). Hit rates per cache are on the usage
page and in `cache_requests_total`.

**Not cached: search results.** With query embeddings and reranker scores cached, a repeated
reranked search already drops from ~2 s to ~70 ms (measured in the Phase 13 evaluation runs);
caching whole result lists would add invalidation (new papers, tags, collections) for little.

### Semantic answer cache

An answer takes 20–90 s on a CPU, and the same question gets asked again. But question
similarity alone is not safe — measured with bge-small:

| Pair | Cosine | Same answer? |
|---|---|---|
| "Does DPR outperform BM25?" / "Does BM25 outperform DPR?" | 0.990 | no |
| "… compared in Table 2?" / "… in Table 3?" | 0.927 | no |
| "… finetune a 65B model?" / "… a 33B model?" | 0.913 | no |
| "What does ColBERT contribute?" / "What is the main contribution of the ColBERT paper?" | 0.846 | yes |

No threshold separates these, so an earlier answer is reused only when **all** of these hold:

1. it was written from the **same passages** (as a set; near-tied reranker scores can swap
   places when only the wording changes, so the reused answer is shown with the passages in
   its own order and its [n] still match) — the library hasn't changed in a way that matters
   and its claim check is still valid;
2. the same model, prompt version and verifier wrote and checked it;
3. both questions started a conversation (follow-ups depend on the history);
4. the earlier answer **passed its check** (well or partially supported) — a cache must not
   spread an answer that failed;
5. cosine ≥ 0.95 *and* the same numbers and names in the same order (QLoRA, BM25, 65B,
   Table 2 — whichever way the user capitalized them).

On the probe pairs this rejected all 10 different-answer pairs and reused 5 of 8 paraphrases;
a miss only costs a fresh answer. A reused answer is labelled ("Reused your answer to … — the
same passages were found") with **Answer again**, which asks without the cache
(`{"fresh": true}`). `ANSWER_CACHE_ENABLED`, `ANSWER_CACHE_MIN_SIMILARITY`,
`ANSWER_CACHE_DAYS` configure it.

Found on the real-model walkthrough and fixed before adopting:

- Requiring the passages in the *same order* missed a plain case-change of the question
  (positions 6–8 swapped) → match on the set and renumber.
- The case-insensitive embedder scored "how much gpu memory…" and "How much GPU memory…"
  1.0, and the tie went to the newer answer — one the checker had marked unsupported →
  only checked answers are reusable; better-checked answers win.
- Timestamps from SQLite are naive: the "asked … ago" label was off by the browser's UTC
  offset → sent as UTC.

Result: a reused answer arrives in **~2.5 s** instead of 40–90 s (search still runs, so the
passages are current; generation and checking are skipped).

## Prometheus and Grafana

`GET /metrics` (Prometheus text format) has:

- this process's histograms and counters: `http_request_duration_ms`, `search_latency_ms`,
  `rerank_latency_ms`, `chat_latency_ms`, `llm_latency_ms`, `cache_requests_total`,
  `answer_cache_total`, …
- language-model usage for **all** processes, read from `llm_usage` at scrape time:
  `llm_usage_calls_total`, `llm_usage_tokens_total`, `llm_usage_cost_usd_total` by feature and
  model. Jobs run in Celery worker processes whose in-memory metrics the API can't see; the
  table has every call, so these series are complete. (Latency histograms of worker-side calls
  are in the table — the usage page — but not in Prometheus.)

```bash
docker compose --profile observability up --build
# Grafana: http://localhost:3000 (admin / $GRAFANA_PASSWORD, default "admin")
# Prometheus: http://localhost:9090
```

The profile adds Prometheus (scraping `backend:8000/metrics` every 15 s) and Grafana with a
provisioned data source and the *Research Intelligence* dashboard
(`infra/observability/grafana/dashboards/research-intelligence.json`): request rate, API /
search / reranking / chat latency percentiles, cache hit rates and answers reused, tokens per
hour by feature, cost per day by model, model calls by status.

*Verification status:* the configuration files are parsed in development (YAML / JSON), and
`/metrics` output is tested; the containers themselves have not been run on the development
machine (no Docker there).

`/metrics` has no authentication, like most scrape endpoints: it carries aggregates only (no
per-user data), but it should not be exposed publicly — restrict it at the proxy in
production (Phase 15 / 16).
