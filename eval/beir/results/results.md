# BEIR scifact results

5183 corpus docs, 300 test queries, 6572 chunks (1296 docs split into more than one chunk).

| Config | nDCG@10 | Recall@10 | Recall@100 | MRR@10 |
|---|---|---|---|---|
| BM25 only | 0.6766 | 0.8134 | 0.9082 | 0.6399 |
| Dense only | 0.7097 | 0.8312 | 0.9433 | 0.6774 |
| Hybrid (RRF) | 0.7170 | 0.8279 | 0.9650 | 0.6850 |
| Hybrid + rerank | 0.6995 | 0.8207 | 0.9650 | 0.6701 |

## Latency (ms/query, CPU-only)

| Config | p50 | p95 | n |
|---|---|---|---|
| bm25_only | 3.5 | 7.2 | 300 |
| dense_only | 67.2 | 79.4 | 300 |
| hybrid_rrf | 71.8 | 84.7 | 300 |
| hybrid_rerank_candidates_100 | 3368.8 | 3764.3 | 300 |
| hybrid_rerank_candidates_30_app_default | 1120.5 | 1291.5 | 300 |

CPU: 12th Gen Intel(R) Core(TM) i5-12400F; none (torch CPU build; all runs are CPU-only)
