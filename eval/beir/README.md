# BEIR retrieval benchmark

A retrieval-quality benchmark on a real, public, labeled IR dataset (BEIR SciFact),
run through this repo's own chunking, BM25, dense (Qdrant) and reranking code —
not the app's synthetic sample papers.

## Why this exists

[docs/EVALUATION.md](../../docs/EVALUATION.md) measures retrieval quality on **your own
uploaded papers and your own questions** (hand-written or model-drafted). That's the right
tool for comparing configurations on your library, but its walkthrough numbers are from
12 synthetic/demo papers with 10 questions — not something you can cite as a general
retrieval result, and the model-drafted questions reuse the source passage's wording,
which structurally favors BM25.

This benchmark instead runs the same retrieval stack against
**[BEIR SciFact](https://github.com/beir-cellar/beir)**: 5,183 real scientific abstracts
and 300 real test queries with human relevance judgments (qrels), the standard academic
retrieval benchmark used to compare BM25/dense/hybrid systems in the literature.

## What it reuses from the app, and what it doesn't

Reused directly (same classes, same formulas, same models, imported from `backend/app`,
not reimplemented):
- `app.services.chunking.Chunker` with the app's configured strategy/size/overlap/contextual
  headers (`backend/app/core/config.py`: `section_aware`, 384 tokens, 64 overlap, headers on).
- `app.services.retrieval.bm25.BM25Index` (the hand-written Okapi BM25) and
  `app.services.retrieval.text.analyze` (the exact tokenizer/stemmer/stopword list).
- `app.services.retrieval.sparse.passage_text` (what BM25 indexes: section title + text).
- `app.services.embeddings.get_embedding_provider` → `BAAI/bge-small-en-v1.5` via
  sentence-transformers, with the app's query/passage prefixes.
- `app.services.vectorstore` (the real Qdrant wrapper, embedded mode) for the dense index.
- `app.services.retrieval.fusion.ReciprocalRankFusion` (RRF, k=60 by default).
- `app.services.reranking.get_reranker` → `cross-encoder/ms-marco-MiniLM-L-6-v2`.

**Not** reused: `app.services.retrieval.service.search()`, the orchestrator the API
actually calls. That function is bound to a SQLAlchemy session and the app's
`Document`/`Chunk` ORM rows (ownership, versions, section filters, snippet highlighting).
BEIR's corpus documents aren't a user's uploaded papers in that schema, so this benchmark
drives the underlying retrieval/fusion/rerank primitives directly instead of standing up a
fake user/document/chunk database just to satisfy that layer. Nothing in `backend/app` is
modified; this only imports and calls existing, unmodified classes.

## Dataset

[BEIR SciFact](https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip)
(claim verification corpus repurposed as a retrieval benchmark):
- 5,183 corpus documents (title + scientific abstract).
- 300 test queries (claims), each with 1+ relevant document(s) in `qrels/test.tsv`
  (339 total relevance judgments, binary).
- Downloaded automatically by `download.py` into `eval/beir/data/scifact/` on first run.

**Granularity note:** qrels are judged at the *document* level, but this app retrieves
*passages* (chunks). Each corpus abstract is run through the real chunker; for most
abstracts that produces exactly one chunk (they're shorter than the 384-token chunk size),
but where an abstract was split into multiple chunks, a retrieved ranking is de-duplicated
to one row per parent document (keeping the best-ranked chunk) before scoring against the
qrels — otherwise a system that merely returns several chunks of the same (irrelevant)
document would look artificially diverse. `results.json` reports how many documents were
split.

## Configurations evaluated

| | Retriever(s) | Fusion | Reranked |
|---|---|---|---|
| a | BM25 only | — | no |
| b | Dense only (Qdrant + bge-small-en-v1.5) | — | no |
| c | BM25 + Dense | Reciprocal Rank Fusion | no |
| d | BM25 + Dense | RRF | cross-encoder (ms-marco-MiniLM-L-6-v2) |

Each retriever returns its own top 100 candidates (`--candidates`, default 100) so
Recall@100 is measurable for every config on equal footing; config d reranks the fused
top 100 for the same reason (`--rerank-candidates`). The app's own production default for
`rerank_candidates` is 30 (faster, less thorough) — `results.json` / `results.md` also
report latency at that setting, labeled `_app_default`.

## Metrics

Computed from scratch in `metrics.py` (stdlib only), matching the standard trec_eval /
`pytrec_eval` / BEIR-harness definitions for binary relevance:
- **nDCG@10** — DCG with log2 rank discount over ideal ordering of the known relevant docs.
- **Recall@10**, **Recall@100** — share of a query's relevant docs found in the top K.
- **MRR@10** — 1 / rank of the first relevant doc in the top 10 (0 if none).

## Reproduce it

One command (uses the backend's own virtualenv so every model/library version matches
the running app):

```powershell
backend\.venv\Scripts\python.exe eval\beir\run_benchmark.py
```

```bash
backend/.venv/bin/python eval/beir/run_benchmark.py
```

Useful flags: `--limit-queries 20` for a fast smoke test, `--candidates`,
`--rerank-candidates`, `--rrf-k`, `--dataset nfcorpus` (any BEIR dataset hosted at the same
URL). Output: `eval/beir/results/results.json` (full machine-readable results, including
hardware and settings snapshot) and `results.md` (the same, as a table).

## Claim verification

Measured — see `claim_verification.py` and `results/claim_verification.json`. BEIR's
SciFact conversion keeps only binary relevance judgments (`qrels/test.tsv`); the
SUPPORT/CONTRADICT labels and cited evidence sentences live in the *original* SciFact
release (`download_claims.py`, from <https://github.com/allenai/scifact>) — the same
underlying 300 dev claims, with gold evidence instead of a document rank.

Method: for each (claim, cited document) pair with annotated evidence, the premise is
the cited gold evidence sentences and the hypothesis is the claim — the same
(premise, hypothesis) shape `app.services.rag.verify.verify_claims` feeds the NLI model
in chat, except the "retrieved passage" is the gold evidence directly, so this measures
the verifier in isolation rather than retrieval + verification together. 112 of 300 dev
claims are `NOT_ENOUGH_INFO` (no gold evidence) and are excluded, leaving 209 instances
(138 SUPPORT, 71 CONTRADICT).

Two numbers are reported, because they tell different stories:

- **`accuracy_app_classify_thresholds`** — what the app actually does: run
  `classify()` (the same thresholds used to judge chat answers) and treat SUPPORTED as
  predicted SUPPORT, anything else (PARTIAL or UNSUPPORTED) as predicted CONTRADICT.
- **`accuracy_raw_argmax_entail_vs_contradict`** — the underlying NLI model's own best
  call (`entailment >= contradiction`), ignoring `classify()`'s thresholds entirely.

`classify()` was tuned to be conservative about calling a RAG answer's claim "supported"
(it requires entailment ≥ 0.5), which is a different, stricter question than "does this
evidence support or contradict the claim" — a claim with entailment 0.3 is `PARTIAL`
in the app (correctly cautious: "not clearly backed"), but that gets scored here as a
wrong answer against a gold CONTRADICT label it never actually asserted. See
`results/claim_verification.json` for the exact numbers and confusion matrices; the raw
argmax number is the fairer read on what the NLI model itself can tell apart.

## Caveats an interviewer could raise

- **5,183 documents is small** next to a production corpus; BM25 does unusually well on
  small, topically-narrow collections like this one.
- **SciFact queries are claims, not questions** — closer to "does this sentence hold" than
  how someone searches a paper library, and the claims share a lot of vocabulary with their
  evidence abstracts (a known BM25-favoring property of this dataset).
- **Chunking barely matters here**: BEIR abstracts are short enough that most become a
  single chunk, so this benchmark doesn't exercise the chunker's section-awareness or
  overlap behavior the way a full paper would. Chunking differences (strategy, size)
  would show up more on the app's real workload (whole papers) than they do here.
- **CPU-only latency**: measured on the machine this ran on (see `results.json` →
  `hardware`), no GPU. Latency for dense embedding and reranking would drop substantially
  on a GPU.
- **RRF/BM25/dense top-k = 100** here (vs. the app's production default of 50) so
  Recall@100 is measurable for every config on equal footing — not the out-of-the-box
  config an end user gets.
- A difference of a few thousandths between two configs on 300 queries can be noise;
  treat the ranking of configs, not the third decimal place, as the finding.
