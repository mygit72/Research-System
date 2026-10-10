import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, CalendarRange, Loader2, Network, Shapes, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Tooltip } from '@/components/ui/Tooltip'
import { useCluster, useTopics } from '@/hooks/useKnowledge'
import { cn } from '@/lib/cn'
import { CLUSTER_METHODS, clusterColor, graphFocusLink, truncate } from '@/lib/knowledge'
import { timeAgo } from '@/lib/format'
import type { ClusterMethod, TopicClustering } from '@/types/api'

const EXCLUDED_REASONS: Record<string, string> = {
  not_indexed: 'not searchable yet',
  other_embedding_model: 'indexed with a different embedding model (reindex to include it)',
  no_vector: 'missing from the search index (reindex to include it)',
}

function silhouetteLabel(value: number | null | undefined) {
  if (value === null || value === undefined) return 'not defined'
  if (value >= 0.5) return 'clearly separated'
  if (value >= 0.25) return 'reasonably separated'
  if (value > 0) return 'overlapping'
  return 'not separated'
}

function ClusterControls({ current, searchable }: { current: TopicClustering | null; searchable: number }) {
  const [method, setMethod] = useState<ClusterMethod>(current?.method ?? 'auto')
  const [k, setK] = useState(current?.params.k ?? 3)
  const [minSize, setMinSize] = useState(current?.params.min_cluster_size ?? 3)
  const cluster = useCluster()
  const tooFew = searchable < 3
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-caption font-medium text-muted">
        Method
        <select
          value={method}
          onChange={(e) => setMethod(e.target.value as ClusterMethod)}
          className="h-9 rounded-md border border-border bg-surface px-2 text-small text-text"
        >
          {(Object.keys(CLUSTER_METHODS) as ClusterMethod[]).map((m) => (
            <option key={m} value={m}>
              {CLUSTER_METHODS[m].label}
            </option>
          ))}
        </select>
      </label>
      {(method === 'kmeans' || method === 'agglomerative') && (
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Topics (k)
          <input
            type="number"
            min={1}
            max={Math.max(1, searchable)}
            value={k}
            onChange={(e) => setK(Number(e.target.value))}
            className="h-9 w-20 rounded-md border border-border bg-surface px-2 text-small text-text"
          />
        </label>
      )}
      {method === 'hdbscan' && (
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Smallest topic
          <input
            type="number"
            min={2}
            max={50}
            value={minSize}
            onChange={(e) => setMinSize(Number(e.target.value))}
            className="h-9 w-20 rounded-md border border-border bg-surface px-2 text-small text-text"
          />
        </label>
      )}
      <Button
        onClick={() =>
          cluster.mutate({
            method,
            k: method === 'kmeans' || method === 'agglomerative' ? k : undefined,
            min_cluster_size: method === 'hdbscan' ? minSize : undefined,
          })
        }
        loading={cluster.isPending}
        disabled={tooFew}
      >
        <Shapes className="size-4" aria-hidden /> {current ? 'Re-cluster' : 'Find topics'}
      </Button>
      <p className="basis-full text-caption text-subtle">
        {tooFew
          ? `Topic clustering needs at least 3 searchable papers (you have ${searchable}).`
          : CLUSTER_METHODS[method].help}
      </p>
    </div>
  )
}

function TopicMap({ run, active, onActive }: { run: TopicClustering; active: number | null; onActive: (id: number | null) => void }) {
  const navigate = useNavigate()
  const size = 400
  const pad = 28
  const at = (v: number) => pad + ((v + 1) / 2) * (size - 2 * pad)
  return (
    <figure>
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="aspect-square w-full rounded-lg border border-border bg-surface"
        role="img"
        aria-label={`Map of ${run.points.length} papers coloured by topic`}
      >
        <line x1={size / 2} y1={pad / 2} x2={size / 2} y2={size - pad / 2} stroke="var(--kg-edge)" strokeDasharray="3 3" />
        <line x1={pad / 2} y1={size / 2} x2={size - pad / 2} y2={size / 2} stroke="var(--kg-edge)" strokeDasharray="3 3" />
        {run.points.map((p) => {
          const dim = active !== null && p.cluster !== active
          return (
            <g
              key={p.document_id}
              transform={`translate(${at(p.x)} ${at(-p.y)})`}
              className="cursor-pointer"
              opacity={dim ? 0.2 : 1}
              onClick={() => navigate(`/papers/${p.document_id}`)}
              onPointerEnter={() => onActive(p.cluster)}
              onPointerLeave={() => onActive(null)}
            >
              <circle
                r={7}
                fill={p.cluster < 0 ? 'var(--surface)' : clusterColor(p.cluster)}
                stroke={p.cluster < 0 ? 'var(--text-subtle)' : 'var(--surface)'}
                strokeWidth={p.cluster < 0 ? 1.5 : 2}
                strokeDasharray={p.cluster < 0 ? '2 2' : undefined}
              />
              <title>{p.title}</title>
            </g>
          )
        })}
      </svg>
      <figcaption className="mt-2 text-caption text-subtle">
        Each dot is a paper, placed by the two main directions of variation of the paper embeddings (PCA)
        {run.quality.variance_2d !== undefined && `, which keep ${Math.round(run.quality.variance_2d * 100)}% of it`}
        . Distances are approximate; colours are the topics. Click a dot to open the paper.
      </figcaption>
    </figure>
  )
}

export function TopicsView() {
  const topics = useTopics()
  const [params] = useSearchParams()
  const requested = params.get('topic')
  const [active, setActive] = useState<number | null>(null)
  const run = topics.data?.clustering ?? null
  const titles = useMemo(() => new Map(run?.points.map((p) => [p.document_id, p.title])), [run])

  useEffect(() => {
    if (requested !== null && run) document.getElementById(`topic-${requested}`)?.scrollIntoView({ block: 'center' })
  }, [requested, run])

  if (topics.isPending) return <Skeleton className="h-96 w-full" />
  if (topics.isError) return <ErrorState error={topics.error} onRetry={() => topics.refetch()} />
  const searchable = topics.data.searchable_papers

  if (!run)
    return (
      <div className="space-y-6">
        <EmptyState
          icon={Shapes}
          className="rounded-lg border border-dashed border-border"
          title="Group your papers into topics"
          description="Papers are grouped by the similarity of their embeddings (title, abstract and keywords). Each topic is described by its most distinctive terms and the methods and datasets its papers share, then named by the AI model."
        />
        <ClusterControls current={null} searchable={searchable} />
      </div>
    )

  const noise = run.points.filter((p) => p.cluster < 0)
  return (
    <div className="space-y-6">
      <ClusterControls key={run.id} current={run} searchable={searchable} />

      {run.stale && (
        <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-small text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{run.stale} Re-cluster to include the changes.</span>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <TopicMap run={run} active={active} onActive={setActive} />
          <dl className="grid grid-cols-2 gap-3 text-small">
            <div>
              <dt className="text-caption text-subtle">Method</dt>
              <dd className="text-text">
                {CLUSTER_METHODS[run.method].label}
                {run.quality.chosen_k ? ` · k = ${run.quality.chosen_k}` : ''}
              </dd>
            </div>
            <div>
              <dt className="text-caption text-subtle">
                <Tooltip content="Silhouette score, −1 to 1: how much closer papers are to their own topic than to the nearest other topic.">
                  <span className="underline decoration-dotted underline-offset-2">Separation</span>
                </Tooltip>
              </dt>
              <dd className="text-text">
                {run.quality.silhouette?.toFixed(2) ?? '–'} · {silhouetteLabel(run.quality.silhouette)}
              </dd>
            </div>
            <div>
              <dt className="text-caption text-subtle">Papers</dt>
              <dd className="text-text">
                {run.paper_count}
                {noise.length > 0 && ` · ${noise.length} in no topic`}
              </dd>
            </div>
            <div>
              <dt className="text-caption text-subtle">Clustered</dt>
              <dd className="text-text">{timeAgo(run.created_at)}</dd>
            </div>
          </dl>
          <p className="flex items-start gap-1.5 text-caption text-subtle">
            {run.naming_status === 'pending' ? (
              <>
                <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin" aria-hidden /> Naming topics with the AI
                model… Until then they’re named after their top terms.
              </>
            ) : run.naming_status === 'done' ? (
              <>
                <Sparkles className="mt-0.5 size-3.5 shrink-0" aria-hidden /> Names written by {run.naming_model} from each
                topic’s titles, terms and entities, kept only if they share words with that topic. Terms
                and papers are shown so you can judge them.{run.error_message ? ` ${run.error_message}` : ''}
              </>
            ) : (
              <>{run.error_message ?? 'Named from their top terms.'}</>
            )}
          </p>
          {run.excluded.length > 0 && (
            <p className="text-caption text-subtle">
              {run.excluded.length} paper{run.excluded.length === 1 ? '' : 's'} not included:{' '}
              {[...new Set(run.excluded.map((e) => EXCLUDED_REASONS[e.reason] ?? e.reason))].join('; ')}.
            </p>
          )}
        </div>

        <ul className="space-y-3">
          {run.clusters.length === 0 && (
            <li>
              <EmptyState
                icon={Shapes}
                title="No dense groups found"
                description="HDBSCAN found no group of papers dense enough to call a topic, so every paper is left unclustered. Try a smaller “smallest topic”, or K-Means."
              />
            </li>
          )}
          {run.clusters.map((cluster) => (
            <li key={cluster.id} id={`topic-${cluster.id}`}>
              <Card
                className={cn(
                  'p-4 transition-shadow',
                  (active === cluster.id || requested === String(cluster.id)) && 'ring-2 ring-[var(--ring)]',
                )}
                onPointerEnter={() => setActive(cluster.id)}
                onPointerLeave={() => setActive(null)}
              >
                <div className="flex items-start gap-3">
                  <span aria-hidden className="mt-1.5 size-3 shrink-0 rounded-full" style={{ background: clusterColor(cluster.id) }} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-body font-semibold text-text">{cluster.name}</h3>
                      <Badge tone={cluster.name_source === 'model' ? 'primary' : 'neutral'}>
                        {cluster.name_source === 'model' ? 'AI-named' : 'from top terms'}
                      </Badge>
                      <span className="text-caption text-subtle">
                        {cluster.size} paper{cluster.size === 1 ? '' : 's'}
                      </span>
                    </div>
                    {cluster.terms.length > 0 && (
                      <p className="mt-1.5 text-small text-muted">
                        <span className="text-subtle">Distinctive terms: </span>
                        {cluster.terms.join(', ')}
                      </p>
                    )}
                    {cluster.entities.length > 0 && (
                      <p className="mt-1 text-small text-muted">
                        <span className="text-subtle">Shared methods & data: </span>
                        {cluster.entities.join(', ')}
                      </p>
                    )}
                    <ul className="mt-2 space-y-0.5">
                      {cluster.document_ids.map((id) => (
                        <li key={id} className="text-small">
                          <Link to={`/papers/${id}`} className="text-text hover:text-primary">
                            {truncate(titles.get(id) ?? 'Untitled', 110)}
                          </Link>
                        </li>
                      ))}
                    </ul>
                    <div className="mt-3 flex flex-wrap gap-3 text-caption">
                      <Link to={`/graph?view=timeline&topic=${cluster.id}`} className="inline-flex items-center gap-1 text-primary hover:underline">
                        <CalendarRange className="size-3.5" aria-hidden /> Timeline
                      </Link>
                      <Link to={graphFocusLink(`topic:${cluster.id}`)} className="inline-flex items-center gap-1 text-primary hover:underline">
                        <Network className="size-3.5" aria-hidden /> In the graph
                      </Link>
                    </div>
                  </div>
                </div>
              </Card>
            </li>
          ))}
          {noise.length > 0 && (
            <li>
              <Card className="p-4">
                <h3 className="text-body font-semibold text-text">In no topic</h3>
                <p className="mt-1 text-small text-muted">HDBSCAN found these papers too far from every dense group.</p>
                <ul className="mt-2 space-y-0.5">
                  {noise.map((p) => (
                    <li key={p.document_id} className="text-small">
                      <Link to={`/papers/${p.document_id}`} className="text-text hover:text-primary">
                        {truncate(p.title, 110)}
                      </Link>
                    </li>
                  ))}
                </ul>
              </Card>
            </li>
          )}
        </ul>
      </div>
    </div>
  )
}
