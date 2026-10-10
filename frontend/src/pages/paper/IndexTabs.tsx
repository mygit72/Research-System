import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Layers, Network, SearchX } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/documents/StatusBadge'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/Card'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { queryClient } from '@/lib/queryClient'
import type { Box } from '@/lib/reader'
import { documentsApi } from '@/services/api'
import type { DocumentDetail } from '@/types/api'

const STRATEGY_LABELS: Record<string, string> = {
  section_aware: 'Section-aware',
  semantic: 'Semantic',
  sentence: 'Sentence',
  recursive: 'Recursive',
  fixed: 'Fixed-size',
}

/** Overview card: is this paper searchable, and with what? */
export function SearchIndexCard({ doc }: { doc: DocumentDetail }) {
  const reindex = useMutation({
    mutationFn: () => documentsApi.reindex(doc.id),
    onSuccess: () => {
      toast.success('Indexing restarted')
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
    onError: (e) => toast.error(e.message),
  })
  const version = doc.version
  const indexing = doc.index_status === 'pending' && doc.processing !== null
  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <CardTitle>Search index</CardTitle>
        {doc.index_status === 'indexed' ? (
          <Badge tone="success">Searchable</Badge>
        ) : doc.index_status === 'failed' ? (
          <Badge tone="error">Not searchable</Badge>
        ) : indexing ? (
          <Badge tone="warning">Indexing…</Badge>
        ) : (
          <Badge>Not indexed</Badge>
        )}
      </CardHeader>
      <CardBody className="space-y-2 text-small">
        {doc.index_status === 'failed' ? (
          <>
            <p className="text-text">
              You can read this paper, but it won't appear in search or chat answers yet.
            </p>
            <p className="text-muted">{doc.index_error}</p>
            <Button size="sm" variant="secondary" loading={reindex.isPending} onClick={() => reindex.mutate()}>
              Retry indexing
            </Button>
          </>
        ) : doc.index_status === 'indexed' && version ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <dt className="text-muted">Passages</dt>
            <dd className="tabular-nums">{version.chunk_count}</dd>
            <dt className="text-muted">Chunking</dt>
            <dd>{STRATEGY_LABELS[version.chunking_strategy ?? ''] ?? version.chunking_strategy}</dd>
            <dt className="text-muted">Embedding model</dt>
            <dd className="truncate font-mono text-caption" title={version.embedding_model ?? ''}>
              {version.embedding_model}
            </dd>
            {version.indexed_at && (
              <>
                <dt className="text-muted">Indexed</dt>
                <dd>{timeAgo(version.indexed_at)}</dd>
              </>
            )}
          </dl>
        ) : indexing ? (
          <p className="text-muted">This paper is being prepared for search.</p>
        ) : (
          <>
            <p className="text-muted">
              This paper hasn't been added to the search index yet, so it won't appear in search
              or chat answers.
            </p>
            <Button size="sm" variant="secondary" loading={reindex.isPending} onClick={() => reindex.mutate()}>
              Index now
            </Button>
          </>
        )}
      </CardBody>
    </Card>
  )
}

export function SimilarTab({ doc }: { doc: DocumentDetail }) {
  const similar = useQuery({
    queryKey: ['documents', 'similar', doc.id, doc.index_status],
    queryFn: () => documentsApi.similar(doc.id),
  })
  if (similar.isPending)
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
    )
  if (similar.isError) return <ErrorState error={similar.error} onRetry={() => similar.refetch()} />
  if (similar.data.status === 'not_indexed')
    return (
      <EmptyState
        icon={SearchX}
        title="Not indexed yet"
        description="Similar papers appear once this paper has been indexed for search."
      />
    )
  if (similar.data.status === 'no_other_papers' || similar.data.items.length === 0)
    return (
      <EmptyState
        icon={Network}
        title="No other papers to compare with"
        description="Upload more papers and we'll show the ones most related to this one."
      />
    )
  return (
    <div>
      <p className="mb-4 text-small text-muted">
        Ranked by semantic similarity of title, abstract and keywords. Reasons are taken from what
        the papers actually share.
      </p>
      <ul className="space-y-3">
        {similar.data.items.map(({ document, score, reasons }) => (
          <li key={document.id}>
            <Card className="p-4 transition-colors hover:border-border-strong">
              <div className="flex items-start gap-4">
                <div className="min-w-0 flex-1">
                  <Link to={`/papers/${document.id}`} className="font-medium text-text hover:text-primary">
                    {document.title}
                  </Link>
                  <p className="mt-0.5 text-small text-muted">
                    {document.authors_display || document.original_filename}
                    {document.year ? ` · ${document.year}` : ''}
                  </p>
                  {reasons.length > 0 && (
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                      {reasons.map((reason) => (
                        <li key={reason}>
                          <Badge tone="primary">{reason}</Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <Tooltip content="Cosine similarity of the papers' embeddings (1.0 = identical)">
                    <span className="text-small font-medium text-text tabular-nums">
                      {score.toFixed(2)}
                    </span>
                  </Tooltip>
                  <StatusBadge doc={document} />
                </div>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  )
}

const KIND_TONES = {
  text: 'neutral',
  table: 'info',
  equation: 'primary',
  caption: 'warning',
  code: 'neutral',
} as const

/** Advanced: the exact retrieval units the search engine sees. */
export function PassagesTab({
  doc,
  onNavigate,
}: {
  doc: DocumentDetail
  onNavigate: (page: number, boxes?: Box[]) => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const chunks = useQuery({
    queryKey: ['documents', 'chunks', doc.id, doc.version?.indexed_at],
    queryFn: () => documentsApi.chunks(doc.id, 500),
    enabled: doc.index_status === 'indexed',
  })
  if (doc.index_status !== 'indexed')
    return (
      <EmptyState
        icon={Layers}
        title="No passages yet"
        description="Passages are created when the paper is indexed for search."
      />
    )
  if (chunks.isPending) return <Skeleton className="h-64 w-full" />
  if (chunks.isError) return <ErrorState error={chunks.error} onRetry={() => chunks.refetch()} />
  const items = chunks.data.items
  const tokens = items.map((c) => c.token_count)
  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-x-6 gap-y-1 text-small text-muted">
        <span>
          <strong className="text-text tabular-nums">{chunks.data.total}</strong> passages
        </span>
        <span>
          {STRATEGY_LABELS[items[0]?.strategy ?? ''] ?? items[0]?.strategy} chunking
        </span>
        <span className="tabular-nums">
          {Math.min(...tokens)}–{Math.max(...tokens)} tokens (avg{' '}
          {Math.round(tokens.reduce((a, b) => a + b, 0) / tokens.length)})
        </span>
      </div>
      <Card>
        <ol className="divide-y divide-border">
          {items.map((chunk) => (
            <li key={chunk.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2 text-caption text-muted">
                <span className="font-mono text-subtle tabular-nums">#{chunk.chunk_index}</span>
                <Badge tone={KIND_TONES[chunk.kind]}>{chunk.kind}</Badge>
                <span className="truncate">{chunk.section_title || 'Front matter'}</span>
                <span>· p. {chunk.page_start}{chunk.page_end !== chunk.page_start && `–${chunk.page_end}`}</span>
                <span className="tabular-nums">· {chunk.token_count} tokens</span>
                <button
                  onClick={() => onNavigate(chunk.page_start, chunk.boxes)}
                  className="ml-auto text-primary hover:underline"
                >
                  Show in paper
                </button>
              </div>
              <button
                onClick={() => setExpanded(expanded === chunk.id ? null : chunk.id)}
                className={cn(
                  'mt-1.5 block w-full text-left text-small whitespace-pre-wrap text-text',
                  expanded !== chunk.id && 'line-clamp-2',
                )}
                aria-expanded={expanded === chunk.id}
              >
                {chunk.text}
              </button>
              {expanded === chunk.id && chunk.context_header && (
                <p className="mt-2 text-caption text-subtle">
                  Embedded with context: <span className="font-mono">{chunk.context_header}</span>
                </p>
              )}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  )
}
