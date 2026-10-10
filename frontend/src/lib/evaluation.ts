import type { EvalMode, EvalRunSummary } from '@/types/api'

/** Shared labels and formatting for the evaluation pages. */

/** Fixed categorical order for runs in charts (validated in light and dark; see index.css). */
export const SERIES = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-4)']

export const MODE_LABELS: Record<EvalMode, string> = { keyword: 'BM25', semantic: 'Dense', hybrid: 'Hybrid (RRF)' }

export const METRIC_HELP: Record<string, string> = {
  'recall@10': 'Share of the expected evidence found in the top 10 passages.',
  'precision@5': 'Share of the top 5 passages that are expected evidence.',
  mrr: 'Mean reciprocal rank: 1 / position of the first relevant passage.',
  'ndcg@10': 'Ranking quality of the top 10, rewarding relevant passages near the top.',
  'paper_recall@5': 'Share of the expected papers among the top 5 passages.',
  faithfulness: 'Share of answer claims the entailment model finds supported by the passages.',
  citation_correctness: 'Share of cited claims whose cited passage supports them.',
  context_recall: 'Share of expected evidence that reached the model.',
  context_precision: 'Share of the passages given to the model that were expected evidence.',
  answer_relevance: 'Similarity of question and answer embeddings — a proxy, not correctness.',
}

export const RETRIEVAL_METRICS = [
  { key: 'recall@10', label: 'Recall@10' },
  { key: 'precision@5', label: 'Precision@5' },
  { key: 'mrr', label: 'MRR' },
  { key: 'ndcg@10', label: 'nDCG@10' },
  { key: 'paper_recall@5', label: 'Paper recall@5' },
]
export const RAG_METRICS = [
  { key: 'faithfulness', label: 'Faithfulness' },
  { key: 'citation_correctness', label: 'Citation correctness' },
  { key: 'context_recall', label: 'Context recall' },
  { key: 'context_precision', label: 'Context precision' },
  { key: 'answer_relevance', label: 'Answer relevance' },
]

export const fmt = (v: number | null | undefined, digits = 3) => (v === null || v === undefined ? '–' : v.toFixed(digits))

export function configLabel(run: Pick<EvalRunSummary, 'kind' | 'config'>) {
  const c = run.config
  return [
    run.kind === 'rag' ? 'RAG' : 'Retrieval',
    MODE_LABELS[c.mode] ?? c.mode,
    c.rerank ? 'reranked' : 'no rerank',
    c.top_k ? `top-k ${c.top_k}` : null,
    c.rrf_k ? `RRF k ${c.rrf_k}` : null,
  ]
    .filter(Boolean)
    .join(' · ')
}
