"""Single-command BEIR retrieval benchmark for this repo's retrieval stack.

Usage (from the repo root, using the backend's own virtualenv):
    backend\\.venv\\Scripts\\python.exe eval\\beir\\run_benchmark.py

What it does:
    1. Downloads BEIR SciFact (if not already in eval/beir/data/) — 5,183 corpus
       abstracts, 300 test queries with binary relevance qrels.
    2. Chunks every corpus document through the app's real Chunker (section_aware,
       384 tokens, 64 overlap, contextual headers — whatever backend/app/core/config.py
       currently defaults to).
    3. Builds a BM25Index (app's hand-written implementation) and a local Qdrant
       collection embedded with the app's configured embedding model
       (BAAI/bge-small-en-v1.5 by default), both isolated under eval/beir/qdrant_storage/
       so this never touches the app's own data.
    4. Runs all 300 test queries through four configs: BM25 only, dense only,
       hybrid RRF, hybrid + cross-encoder rerank.
    5. Scores each against the official qrels with nDCG@10 / Recall@10 / Recall@100 /
       MRR@10 (hand-rolled, trec_eval-equivalent — see metrics.py).
    6. Measures per-query retrieval latency (p50/p95) for the hybrid and
       hybrid+rerank configs, on this machine, CPU only.
    7. Writes eval/beir/results/results.json and results.md.

Nothing here modifies backend/app — it only imports and calls existing classes.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dataset import load_corpus, load_qrels, load_queries  # noqa: E402
from download import download  # noqa: E402
from metrics import aggregate, score_query  # noqa: E402
from pipeline import (  # noqa: E402
    build_bm25,
    build_dense,
    build_settings,
    bm25_search,
    chunk_corpus,
    dense_search,
    fuse,
    get_embedding_provider,
    get_reranker,
    keys_to_docs,
    rerank_keys,
)

CONFIG_NAMES = {
    "bm25": "BM25 only",
    "dense": "Dense only",
    "hybrid_rrf": "Hybrid (RRF)",
    "hybrid_rerank": "Hybrid + rerank",
}


def cpu_info() -> str:
    try:
        import subprocess

        out = subprocess.run(
            ["wmic", "cpu", "get", "name"], capture_output=True, text=True, timeout=10
        )
        lines = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        if len(lines) > 1:
            return lines[1]
    except Exception:
        pass
    return platform.processor() or "unknown CPU"


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="scifact")
    parser.add_argument("--data-dir", default=str(HERE / "data"))
    parser.add_argument("--candidates", type=int, default=100, help="per-retriever top-k before fusion")
    parser.add_argument("--rerank-candidates", type=int, default=100)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--limit-queries", type=int, default=0, help="0 = all test queries")
    parser.add_argument("--out-dir", default=str(HERE / "results"))
    parser.add_argument("--qdrant-dir", default=str(HERE / "qdrant_storage"))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    dataset_dir = download(args.dataset, data_dir)
    docs = load_corpus(dataset_dir)
    queries = load_queries(dataset_dir)
    qrels = load_qrels(dataset_dir, "test")
    test_qids = sorted(qrels.keys(), key=int)
    if args.limit_queries:
        test_qids = test_qids[: args.limit_queries]
    print(f"[data] {len(docs)} corpus docs, {len(test_qids)} test queries, "
          f"{sum(len(v) for v in qrels.values())} qrel judgments")

    settings = build_settings(
        Path(args.qdrant_dir),
        rrf_k=args.rrf_k,
        rerank_candidates=args.rerank_candidates,
        top_k=args.candidates,
    )
    print(f"[config] embedding_model={settings.embedding_model} reranker_model={settings.reranker_model} "
          f"chunking_strategy={settings.chunking_strategy} chunk_size={settings.chunk_size} "
          f"bm25(k1={settings.bm25_k1},b={settings.bm25_b}) rrf_k={settings.rrf_k}")

    t_chunk = time.perf_counter()
    chunks = chunk_corpus(docs, settings)
    chunk_by_key = {c.key: c for c in chunks}
    per_doc: dict[str, int] = {}
    for c in chunks:
        per_doc[c.doc_id] = per_doc.get(c.doc_id, 0) + 1
    split_docs = sum(1 for n in per_doc.values() if n > 1)
    print(f"[chunk] {len(chunks)} chunks from {len(per_doc)} docs in "
          f"{time.perf_counter() - t_chunk:.1f}s ({split_docs} docs split into >1 chunk, "
          f"max {max(per_doc.values())} chunks/doc)")

    t_bm25 = time.perf_counter()
    bm25_index = build_bm25(chunks, settings)
    print(f"[bm25] indexed {bm25_index.size} passages in {time.perf_counter() - t_bm25:.1f}s")

    t_dense = time.perf_counter()
    collection, uuid_to_key = build_dense(chunks, settings)
    dense_build_s = time.perf_counter() - t_dense
    print(f"[dense] embedded + indexed {len(chunks)} passages in {dense_build_s:.1f}s "
          f"-> collection {collection}")

    reranker = get_reranker(settings)
    provider = get_embedding_provider(settings)
    # Warm up lazy model loads so the first timed query isn't penalized by a one-time load.
    provider.embed_query("warm up")
    reranker.score("warm up", ["warm up passage"])

    per_config_scores: dict[str, list] = {k: [] for k in CONFIG_NAMES}
    latency_bm25: list[float] = []
    latency_dense: list[float] = []
    latency_hybrid: list[float] = []
    latency_rerank: list[float] = []

    for qi, qid in enumerate(test_qids, start=1):
        query = queries[qid]
        relevant = qrels[qid]

        t = time.perf_counter()
        bm25_hits = bm25_search(bm25_index, query, args.candidates)
        latency_bm25.append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        dense_hits = dense_search(settings, collection, uuid_to_key, query, args.candidates)
        t_dense_q = time.perf_counter() - t
        latency_dense.append(t_dense_q * 1000)

        t = time.perf_counter()
        fused_keys = fuse({"bm25": bm25_hits, "dense": dense_hits}, args.rrf_k, args.candidates)
        t_fuse_q = time.perf_counter() - t
        latency_hybrid.append((latency_bm25[-1] / 1000 + t_dense_q + t_fuse_q) * 1000)

        head = fused_keys[: args.rerank_candidates]
        t = time.perf_counter()
        reranked_keys = rerank_keys(reranker, query, head, chunk_by_key)
        t_rerank_q = time.perf_counter() - t
        latency_rerank.append((latency_bm25[-1] / 1000 + t_dense_q + t_fuse_q + t_rerank_q) * 1000)

        results = {
            "bm25": keys_to_docs([k for k, _ in bm25_hits], chunk_by_key),
            "dense": keys_to_docs([k for k, _ in dense_hits], chunk_by_key),
            "hybrid_rrf": keys_to_docs(fused_keys, chunk_by_key),
            "hybrid_rerank": keys_to_docs(reranked_keys, chunk_by_key),
        }
        for name, ranked_docs in results.items():
            per_config_scores[name].append(score_query(qid, ranked_docs, relevant))
        if qi % 50 == 0:
            print(f"[eval] {qi}/{len(test_qids)} queries")

    table = {CONFIG_NAMES[k]: aggregate(v) for k, v in per_config_scores.items()}

    # Secondary latency point at the app's production default rerank_candidates (30),
    # scored on the already-fused rankings (no need to re-retrieve).
    default_rerank_candidates = 30
    latency_rerank_default: list[float] = []
    for qid in test_qids:
        query = queries[qid]
        bm25_hits = bm25_search(bm25_index, query, args.candidates)
        t = time.perf_counter()
        dense_hits = dense_search(settings, collection, uuid_to_key, query, args.candidates)
        t_dense_q = time.perf_counter() - t
        t = time.perf_counter()
        fused_keys = fuse({"bm25": bm25_hits, "dense": dense_hits}, args.rrf_k, args.candidates)
        t_fuse_q = time.perf_counter() - t
        head = fused_keys[:default_rerank_candidates]
        t = time.perf_counter()
        rerank_keys(reranker, query, head, chunk_by_key)
        t_rerank_q = time.perf_counter() - t
        latency_rerank_default.append((t_dense_q + t_fuse_q + t_rerank_q) * 1000)

    results = {
        "dataset": args.dataset,
        "n_corpus_docs": len(docs),
        "n_test_queries": len(test_qids),
        "chunks": len(chunks),
        "docs_split_into_multiple_chunks": split_docs,
        "settings": {
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.reranker_model,
            "chunking_strategy": settings.chunking_strategy,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "bm25_k1": settings.bm25_k1,
            "bm25_b": settings.bm25_b,
            "rrf_k": settings.rrf_k,
            "candidates_per_retriever": args.candidates,
            "rerank_candidates_for_table": args.rerank_candidates,
        },
        "hardware": {
            "cpu": cpu_info(),
            "gpu": "none (torch CPU build; all runs are CPU-only)",
            "python": platform.python_version(),
            "os": platform.platform(),
        },
        "metrics": table,
        "latency_ms": {
            "bm25_only": {
                "p50": round(percentile(latency_bm25, 0.50), 2),
                "p95": round(percentile(latency_bm25, 0.95), 2),
                "n": len(latency_bm25),
            },
            "dense_only": {
                "p50": round(percentile(latency_dense, 0.50), 2),
                "p95": round(percentile(latency_dense, 0.95), 2),
                "n": len(latency_dense),
            },
            "hybrid_rrf": {
                "p50": round(percentile(latency_hybrid, 0.50), 2),
                "p95": round(percentile(latency_hybrid, 0.95), 2),
                "n": len(latency_hybrid),
            },
            f"hybrid_rerank_candidates_{args.rerank_candidates}": {
                "p50": round(percentile(latency_rerank, 0.50), 2),
                "p95": round(percentile(latency_rerank, 0.95), 2),
                "n": len(latency_rerank),
            },
            f"hybrid_rerank_candidates_{default_rerank_candidates}_app_default": {
                "p50": round(percentile(latency_rerank_default, 0.50), 2),
                "p95": round(percentile(latency_rerank_default, 0.95), 2),
                "n": len(latency_rerank_default),
            },
        },
        "wall_clock_seconds": round(time.perf_counter() - t0, 1),
        "dense_index_build_seconds": round(dense_build_s, 1),
    }

    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_markdown(results, out_dir / "results.md")
    print(f"\n[done] wrote {out_dir / 'results.json'} and {out_dir / 'results.md'}")
    print(json.dumps(table, indent=2))


def write_markdown(results: dict, path: Path) -> None:
    lines = [
        f"# BEIR {results['dataset']} results",
        "",
        f"{results['n_corpus_docs']} corpus docs, {results['n_test_queries']} test queries, "
        f"{results['chunks']} chunks ({results['docs_split_into_multiple_chunks']} docs split "
        "into more than one chunk).",
        "",
        "| Config | nDCG@10 | Recall@10 | Recall@100 | MRR@10 |",
        "|---|---|---|---|---|",
    ]
    for name, m in results["metrics"].items():
        lines.append(
            f"| {name} | {m['nDCG@10']:.4f} | {m['Recall@10']:.4f} | "
            f"{m['Recall@100']:.4f} | {m['MRR@10']:.4f} |"
        )
    lines += ["", "## Latency (ms/query, CPU-only)", "", "| Config | p50 | p95 | n |", "|---|---|---|---|"]
    for name, lat in results["latency_ms"].items():
        lines.append(f"| {name} | {lat['p50']:.1f} | {lat['p95']:.1f} | {lat['n']} |")
    lines += ["", f"CPU: {results['hardware']['cpu']}; {results['hardware']['gpu']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
