import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Expand, ExternalLink, Network, Route, Search, X } from 'lucide-react'
import { GraphCanvas } from '@/components/knowledge/GraphCanvas'
import { TypeDot } from '@/components/knowledge/Entities'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { buttonClass } from '@/lib/buttonStyles'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { useDebounced } from '@/hooks/useDebounced'
import { useGraph } from '@/hooks/useKnowledge'
import { cn } from '@/lib/cn'
import { DEFAULT_GRAPH_TYPES, NODE_META, NODE_TYPES, RELATION_LABELS, REVERSE_RELATION_LABELS, nodeLink } from '@/lib/knowledge'
import { knowledgeApi } from '@/services/api'
import type { GraphEdge, GraphNode, KnowledgeGraph, NodeType } from '@/types/api'
import { toast } from 'sonner'

const edgeKey = (e: GraphEdge) => `${e.source}|${e.target}|${e.relation}`

function merge(base: KnowledgeGraph, extra: KnowledgeGraph[]) {
  const nodes = new Map(base.nodes.map((n) => [n.id, n]))
  const edges = new Map(base.edges.map((e) => [edgeKey(e), e]))
  for (const g of extra) {
    for (const n of g.nodes) nodes.set(n.id, n)
    for (const e of g.edges) edges.set(edgeKey(e), e)
  }
  // "More connections" counts are relative to what is on screen now.
  const shown = new Map<string, number>()
  for (const e of edges.values()) {
    shown.set(e.source, (shown.get(e.source) ?? 0) + 1)
    shown.set(e.target, (shown.get(e.target) ?? 0) + 1)
  }
  return {
    nodes: [...nodes.values()].map((n) => ({ ...n, hidden_neighbors: Math.max(0, n.degree - (shown.get(n.id) ?? 0)) })),
    edges: [...edges.values()],
  }
}

function NodeSearch({ placeholder, onPick }: { placeholder: string; onPick: (node: GraphNode) => void }) {
  const [text, setText] = useState('')
  const q = useDebounced(text.trim(), 200)
  const hits = useQuery({ queryKey: ['knowledge', 'search', q], queryFn: () => knowledgeApi.search(q), enabled: q.length > 0 })
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-subtle" aria-hidden />
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="pl-8"
      />
      {q && hits.data && (
        <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-border bg-surface-elevated p-1 shadow-lg">
          {hits.data.length === 0 && <li className="px-2 py-1.5 text-small text-muted">Nothing matches “{q}”.</li>}
          {hits.data.map((node) => (
            <li key={node.id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-small hover:bg-surface-muted"
                onClick={() => {
                  onPick(node)
                  setText('')
                }}
              >
                <TypeDot type={node.type} />
                <span className="min-w-0 flex-1 truncate">{node.label}</span>
                <span className="text-caption text-subtle">{NODE_META[node.type].label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function NodeDetails({
  node,
  onExpand,
  onFocus,
  onPath,
  expanding,
}: {
  node: GraphNode
  onExpand: () => void
  onFocus: () => void
  onPath: (target: GraphNode) => void
  expanding: boolean
}) {
  const meta = NODE_META[node.type]
  const link = nodeLink(node)
  const facts = [
    node.data.year ? `${node.data.year}` : null,
    typeof node.data.venue === 'string' && node.data.venue ? node.data.venue : null,
    typeof node.data.papers === 'number' && node.type !== 'paper' ? `${node.data.papers} paper${node.data.papers === 1 ? '' : 's'}` : null,
    node.data.source === 'discovered' ? 'found in your papers' : null,
  ].filter(Boolean)
  return (
    <div className="space-y-4">
      <div>
        <Badge>
          <TypeDot type={node.type} /> {meta.label}
        </Badge>
        <h2 className="mt-2 text-h3 text-text">{node.label}</h2>
        {typeof node.data.authors === 'string' && node.data.authors && <p className="mt-1 text-small text-muted">{node.data.authors}</p>}
        {facts.length > 0 && <p className="mt-1 text-small text-muted">{facts.join(' · ')}</p>}
        <p className="mt-1 text-caption text-subtle">
          {node.degree} connection{node.degree === 1 ? '' : 's'} with the current filters
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {link && (
          <Link to={link} className={buttonClass('secondary', 'sm')}>
            <ExternalLink className="size-3.5" aria-hidden /> Open
          </Link>
        )}
        <Button variant="secondary" size="sm" onClick={onExpand} loading={expanding} disabled={node.hidden_neighbors === 0}>
          <Expand className="size-3.5" aria-hidden />
          {node.hidden_neighbors ? `Show ${node.hidden_neighbors} more` : 'All shown'}
        </Button>
        <Button variant="ghost" size="sm" onClick={onFocus}>
          <Network className="size-3.5" aria-hidden /> Focus
        </Button>
      </div>
      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-small font-medium text-text">
          <Route className="size-4 text-subtle" aria-hidden /> How is it connected to…
        </p>
        <NodeSearch placeholder="Another paper, author, dataset…" onPick={onPath} />
      </div>
    </div>
  )
}

export function GraphView() {
  const [params, setParams] = useSearchParams()
  const focus = params.get('focus') ?? undefined
  const [types, setTypes] = useState<NodeType[]>(DEFAULT_GRAPH_TYPES)
  const [mentions, setMentions] = useState(false)
  const [limit, setLimit] = useState(60)
  const graph = useGraph({ types: types.join(','), limit, focus, includeMentions: mentions })
  const [extra, setExtra] = useState<KnowledgeGraph[]>([])
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [path, setPath] = useState<KnowledgeGraph | null>(null)
  const [expanding, setExpanding] = useState(false)

  // New overview (filters changed): drop expansions and the highlighted path.
  const [base, setBase] = useState(graph.data)
  if (base !== graph.data) {
    setBase(graph.data)
    setExtra([])
    setPath(null)
  }

  const merged = useMemo(() => (graph.data ? merge(graph.data, path ? [...extra, path] : extra) : null), [graph.data, extra, path])
  const selectedNode = selected && merged ? (merged.nodes.find((n) => n.id === selected.id) ?? selected) : null
  const highlight = useMemo(() => (path ? new Set(path.nodes.map((n) => n.id)) : null), [path])

  const expand = async (node: GraphNode) => {
    setExpanding(true)
    try {
      const more = await knowledgeApi.neighbors(node.id, { types: types.join(','), includeMentions: mentions, limit: 25 })
      setExtra((current) => [...current, more])
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setExpanding(false)
    }
  }

  const pick = async (node: GraphNode) => {
    setSelected(node)
    if (!merged?.nodes.some((n) => n.id === node.id)) await expand(node)
  }

  const findPath = async (target: GraphNode) => {
    if (!selectedNode) return
    try {
      setPath(await knowledgeApi.path(selectedNode.id, target.id))
    } catch (error) {
      toast.error((error as Error).message)
    }
  }

  const toggleType = (type: NodeType) =>
    setTypes((current) => (current.includes(type) ? current.filter((t) => t !== type) : [...current, type]))

  if (graph.isPending) return <Skeleton className="h-[60vh] w-full" />
  if (graph.isError) return <ErrorState error={graph.error} onRetry={() => graph.refetch()} />
  if (graph.data.paper_count === 0)
    return (
      <EmptyState
        icon={Network}
        className="rounded-lg border border-dashed border-border"
        title="No papers yet"
        description="Upload papers and the graph fills in: their authors, the datasets, models and methods they use or propose, and which of them cite each other."
        actions={
          <Link to="/papers" className={buttonClass()}>
            Go to the library
          </Link>
        }
      />
    )

  const status = graph.data.entity_status
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="lg:w-72">
          <NodeSearch placeholder="Find a paper, author, dataset…" onPick={pick} />
        </div>
        <fieldset className="flex flex-wrap items-center gap-1.5">
          <legend className="sr-only">Show node types</legend>
          {NODE_TYPES.map((type) => {
            const on = types.includes(type)
            const hidden = graph.data.hidden[type]
            return (
              <button
                key={type}
                type="button"
                aria-pressed={on}
                onClick={() => toggleType(type)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-caption font-medium transition-colors',
                  on ? 'border-border-strong bg-surface text-text' : 'border-dashed border-border text-subtle hover:text-muted',
                )}
                title={on && hidden ? `${hidden} more not shown — raise the limit or expand a node` : undefined}
              >
                <TypeDot type={type} className={on ? '' : 'opacity-40'} />
                {NODE_META[type].plural}
                {on && hidden ? <span className="text-subtle tabular-nums">+{hidden}</span> : null}
              </button>
            )
          })}
        </fieldset>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-small text-muted">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={mentions} onChange={(e) => setMentions(e.target.checked)} className="accent-[var(--primary)]" />
          Include passing mentions
        </label>
        <label className="flex items-center gap-2">
          Show up to
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="h-8 rounded-md border border-border bg-surface px-2 text-small text-text"
          >
            {[30, 60, 120, 200].map((n) => (
              <option key={n} value={n}>
                {n} nodes
              </option>
            ))}
          </select>
        </label>
        {focus && (
          <Button variant="ghost" size="sm" onClick={() => setParams((p) => (p.delete('focus'), p))}>
            <X className="size-3.5" aria-hidden /> Back to the overview
          </Button>
        )}
        <span className="text-caption text-subtle sm:ml-auto">
          {graph.data.paper_count} papers · {status.entities ?? 0} entities · {status.authors ?? 0} authors ·{' '}
          {status.citations ?? 0} citations between your papers · {status.topics ?? 0} topics
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <GraphCanvas
          className={cn('h-[62vh] min-h-[420px] transition-opacity', graph.isPlaceholderData && 'opacity-60')}
          nodes={merged!.nodes}
          edges={merged!.edges}
          selectedId={selectedNode?.id ?? null}
          highlight={highlight}
          onSelect={(node) => {
            setSelected(node)
            if (!node) setPath(null)
          }}
          onExpand={expand}
        />
        <aside aria-label="Graph details" className="rounded-lg border border-border bg-surface p-4" aria-live="polite">
          {path ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-small font-semibold text-text">Connection ({path.edges.length} steps)</h2>
                <Button variant="ghost" size="icon-sm" aria-label="Clear the connection" onClick={() => setPath(null)}>
                  <X className="size-4" aria-hidden />
                </Button>
              </div>
              <ol className="space-y-2">
                {path.nodes.map((node, i) => {
                  const edge = path.edges.find(
                    (e) =>
                      (e.source === node.id && e.target === path.nodes[i + 1]?.id) ||
                      (e.target === node.id && e.source === path.nodes[i + 1]?.id),
                  )
                  return (
                    <li key={node.id}>
                      <button type="button" onClick={() => setSelected(node)} className="flex items-center gap-2 text-left text-small text-text hover:text-primary">
                        <TypeDot type={node.type} />
                        <span className="line-clamp-2">{node.label}</span>
                      </button>
                      {edge && (
                        <p className="ml-4 flex items-center gap-1 py-0.5 text-caption text-subtle">
                          <ArrowRight className="size-3" aria-hidden />
                          {(edge.source === node.id ? RELATION_LABELS : REVERSE_RELATION_LABELS)[edge.relation] ?? edge.relation}
                        </p>
                      )}
                    </li>
                  )
                })}
              </ol>
            </div>
          ) : selectedNode ? (
            <NodeDetails
              node={selectedNode}
              expanding={expanding}
              onExpand={() => expand(selectedNode)}
              onFocus={() => setParams((p) => (p.set('focus', selectedNode.id), p))}
              onPath={findPath}
            />
          ) : (
            <div className="space-y-3 text-small text-muted">
              <h2 className="font-semibold text-text">Explore</h2>
              <p>
                Showing the {merged!.nodes.length} most connected nodes. Click a node for details, double-click (or “Show
                more”) to expand it. Drag to pan, scroll to zoom.
              </p>
              <p>
                Links come from your papers: authors from their metadata, citations from reference lists that match
                another paper in your library, and datasets, models and methods from the text (each link keeps the
                sentences it was found in).
              </p>
              {(status.topics ?? 0) === 0 && (
                <p>
                  Topics appear after you{' '}
                  <Link to="/graph?view=topics" className="text-primary underline underline-offset-2">
                    cluster your papers
                  </Link>
                  .
                </p>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
