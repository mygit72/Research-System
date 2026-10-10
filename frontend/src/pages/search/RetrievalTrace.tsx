import { Card, CardHeader, CardTitle } from '@/components/ui/Card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { RETRIEVER_LABELS } from '@/lib/search'
import type { SearchResponse, TraceEntry } from '@/types/api'

const STAGE_NAMES: Record<string, string> = {
  reranked: 'Reranked',
  fused: 'Fused (RRF)',
  bm25: 'BM25',
  postgres_fts: 'PostgreSQL FTS',
  dense: 'Dense',
}

const TIMING_NAMES: Record<string, string> = {
  scope: 'Filters',
  bm25: 'BM25',
  postgres_fts: 'FTS',
  dense: 'Dense',
  fusion: 'Fusion',
  rerank: 'Rerank',
  load: 'Load passages',
  total: 'Total',
}

function Movement({ from, to }: { from: number; to: number }) {
  const delta = from - to
  return (
    <span className="tabular-nums">
      <span className="text-muted">was #{from}</span>{' '}
      {delta > 0 ? (
        <span className="text-success">▲{delta}</span>
      ) : delta < 0 ? (
        <span className="text-error">▼{-delta}</span>
      ) : (
        <span className="text-subtle">=</span>
      )}
    </span>
  )
}

function Detail({ stage, entry }: { stage: string; entry: TraceEntry }) {
  if (stage === 'reranked' && entry.fused_rank !== undefined) {
    return <Movement from={entry.fused_rank} to={entry.rank} />
  }
  if (stage === 'fused' && entry.contributions) {
    return (
      <span className="text-muted">
        {Object.entries(entry.contributions)
          .map(([name, c]) => `${RETRIEVER_LABELS[name] ?? name} #${c.rank} → ${c.rrf.toFixed(4)}`)
          .join(' + ')}
      </span>
    )
  }
  if (entry.matched_terms) {
    return (
      <span className="font-mono text-muted">
        {Object.entries(entry.matched_terms)
          .map(([term, tf]) => `${term}×${tf}`)
          .join(' ')}
      </span>
    )
  }
  return null
}

function StageTable({ stage, entries }: { stage: string; entries: TraceEntry[] }) {
  if (entries.length === 0)
    return <p className="px-5 py-6 text-small text-muted">This retriever returned nothing.</p>
  const detailHeading =
    stage === 'reranked'
      ? 'Before reranking'
      : stage === 'fused'
        ? 'Contributions'
        : stage === 'dense'
          ? ''
          : 'Matched terms (tf)'
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full text-left text-caption">
        <thead className="sticky top-0 bg-surface text-subtle">
          <tr className="border-b border-border">
            <th scope="col" className="px-5 py-2 font-medium">#</th>
            <th scope="col" className="px-2 py-2 font-medium">
              {stage === 'dense' ? 'Cosine' : stage === 'reranked' ? 'Relevance' : 'Score'}
            </th>
            <th scope="col" className="px-2 py-2 font-medium">Passage</th>
            {detailHeading && (
              <th scope="col" className="px-2 py-2 pr-5 font-medium">{detailHeading}</th>
            )}
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.chunk_id} className="border-b border-border last:border-0 align-top">
              <td className="px-5 py-2 text-subtle tabular-nums">{entry.rank}</td>
              <td className="px-2 py-2 font-mono tabular-nums">{entry.score.toFixed(4)}</td>
              <td className="max-w-md px-2 py-2">
                {entry.missing ? (
                  <span className="text-subtle">Passage no longer exists (re-indexed)</span>
                ) : (
                  <>
                    <span className="block truncate text-text">{entry.document_title}</span>
                    <span className="block truncate text-muted">
                      {entry.section_title || 'Front matter'} · p. {entry.page}
                    </span>
                  </>
                )}
              </td>
              {detailHeading && (
                <td className="px-2 py-2 pr-5">
                  <Detail stage={stage} entry={entry} />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** "How were these results found?" Every stage of the pipeline, for technical users. */
export function RetrievalTrace({ response }: { response: SearchResponse }) {
  const trace = response.trace
  if (!trace) return null
  const order = ['reranked', 'fused', 'bm25', 'postgres_fts', 'dense'].filter((s) => trace.stages[s])
  const params = trace.parameters
  return (
    <Card className="overflow-hidden">
      <CardHeader className="space-y-3">
        <CardTitle className="text-body font-semibold">How these results were found</CardTitle>
        <dl className="flex flex-wrap gap-x-5 gap-y-1 text-caption">
          {Object.entries(response.timings_ms).map(([stage, ms]) => (
            <div key={stage} className="flex gap-1">
              <dt className="text-muted">{TIMING_NAMES[stage] ?? stage}</dt>
              <dd className="font-mono text-text tabular-nums">{ms} ms</dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-wrap items-center gap-1.5 text-caption">
          <span className="text-muted">Query terms after stemming:</span>
          {trace.query_terms.length ? (
            trace.query_terms.map((term) => (
              <code key={term} className="rounded-sm bg-surface-muted px-1.5 py-0.5 text-text">
                {term}
              </code>
            ))
          ) : (
            <span className="text-subtle">none (only stopwords)</span>
          )}
        </div>
        <p className="text-caption text-muted">
          {trace.fusion ? `RRF k = ${trace.fusion.k} · ` : ''}
          BM25 k1 = {String(params.bm25_k1)}, b = {String(params.bm25_b)} · up to{' '}
          {String(params.candidates_per_retriever)} candidates per retriever · embedding model{' '}
          <code>{String(params.embedding_model)}</code>
          {params.reranker
            ? ` · reranker ${String(params.reranker)} over the top ${String(params.rerank_candidates)}`
            : ''}
          {Array.isArray(params.excluded_sections) && params.excluded_sections.length > 0
            ? ` · excluded: ${params.excluded_sections.join(', ')}`
            : ''}
        </p>
      </CardHeader>
      <Tabs defaultValue={order[0]}>
        <TabsList className="px-3">
          {order.map((stage) => (
            <TabsTrigger key={stage} value={stage} count={trace.stages[stage].length}>
              {STAGE_NAMES[stage] ?? stage}
            </TabsTrigger>
          ))}
        </TabsList>
        {order.map((stage) => (
          <TabsContent key={stage} value={stage}>
            <StageTable stage={stage} entries={trace.stages[stage]} />
          </TabsContent>
        ))}
      </Tabs>
    </Card>
  )
}
