import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Check, FlaskConical, Loader2, Plus, Search, Sparkles, Trash2, X } from 'lucide-react'
import { MetricBars } from '@/components/evaluation/MetricBars'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { Tooltip } from '@/components/ui/Tooltip'
import { useDebounced } from '@/hooks/useDebounced'
import { useDatasets, useEvalAction, useItems, useRuns } from '@/hooks/useEvaluation'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { evaluationApi, searchApi } from '@/services/api'
import { METRIC_HELP, MODE_LABELS, RAG_METRICS, RETRIEVAL_METRICS, SERIES, configLabel, fmt } from '@/lib/evaluation'
import type { EvalMode } from '@/types/api'

// --- runs -----------------------------------------------------------------------------------------

function StartRun() {
  const datasets = useDatasets()
  const [datasetId, setDatasetId] = useState('')
  const [kind, setKind] = useState<'retrieval' | 'rag'>('retrieval')
  const [mode, setMode] = useState<EvalMode>('hybrid')
  const [rerank, setRerank] = useState(true)
  const [topK, setTopK] = useState('')
  const [rrfK, setRrfK] = useState('')
  const [name, setName] = useState('')
  const start = useEvalAction(
    () =>
      evaluationApi.startRun(datasetId, {
        name,
        kind,
        config: { mode, rerank, ...(topK ? { top_k: Number(topK) } : {}), ...(rrfK ? { rrf_k: Number(rrfK) } : {}) },
      }),
    'Run started',
  )
  const usable = datasets.data?.filter((d) => d.verified > 0) ?? []
  return (
    <Card className="p-4">
      <h2 className="text-small font-semibold text-text">New run</h2>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Dataset
          <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)} className="h-9 rounded-md border border-border bg-surface px-2 text-small text-text">
            <option value="">Choose…</option>
            {usable.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.verified} questions)
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Measure
          <select value={kind} onChange={(e) => setKind(e.target.value as 'retrieval' | 'rag')} className="h-9 rounded-md border border-border bg-surface px-2 text-small text-text">
            <option value="retrieval">Retrieval only (fast)</option>
            <option value="rag">Retrieval + answers (slow)</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Retriever
          <select value={mode} onChange={(e) => setMode(e.target.value as EvalMode)} className="h-9 rounded-md border border-border bg-surface px-2 text-small text-text">
            {(Object.keys(MODE_LABELS) as EvalMode[]).map((m) => (
              <option key={m} value={m}>
                {MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-small text-text">
          <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} className="accent-[var(--primary)]" />
          Rerank
        </label>
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Candidates (top-k)
          <input type="number" min={5} max={200} placeholder="default" value={topK} onChange={(e) => setTopK(e.target.value)} className="h-9 w-24 rounded-md border border-border bg-surface px-2 text-small text-text" />
        </label>
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          RRF k
          <input type="number" min={1} max={500} placeholder="default" value={rrfK} onChange={(e) => setRrfK(e.target.value)} className="h-9 w-24 rounded-md border border-border bg-surface px-2 text-small text-text" />
        </label>
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. hybrid, no rerank" className="h-9 w-48 rounded-md border border-border bg-surface px-2 text-small text-text" />
        </label>
        <Button onClick={() => start.mutate(undefined)} disabled={!datasetId} loading={start.isPending}>
          <FlaskConical className="size-4" aria-hidden /> Run
        </Button>
      </div>
      <p className="mt-2 text-caption text-subtle">
        {kind === 'rag'
          ? 'Answers each question with the language model (up to 25; ~20–60 s each on a CPU) and checks every claim.'
          : 'Searches each question and scores the ranking against the expected passages.'}{' '}
        Embedding model and chunking come from your current index — re-index to compare those.
      </p>
      {datasets.data && usable.length === 0 && (
        <p className="mt-2 text-small text-muted">Create a dataset with verified questions first (Datasets tab).</p>
      )}
    </Card>
  )
}

function RunsView() {
  const runs = useRuns()
  const [, setParams] = useSearchParams()
  const [picked, setPicked] = useState<string[]>([])
  const remove = useEvalAction((id: string) => evaluationApi.deleteRun(id))
  if (runs.isPending) return <Skeleton className="h-48 w-full" />
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-4)))
  return (
    <div className="space-y-6">
      <StartRun />
      {runs.data.length === 0 ? (
        <EmptyState icon={FlaskConical} className="rounded-lg border border-dashed border-border" title="No runs yet" description="Start one above to measure retrieval or answer quality on a dataset." />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              disabled={picked.length < 2}
              onClick={() => setParams({ view: 'compare', runs: picked.join(',') })}
            >
              Compare {picked.length ? `(${picked.length})` : ''}
            </Button>
            <span className="text-caption text-subtle">Tick 2–4 runs on the same dataset to compare them.</span>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[760px] text-small">
              <thead className="bg-surface-muted text-left text-caption text-muted">
                <tr>
                  <th className="w-8 px-3 py-2" />
                  <th className="px-3 py-2 font-medium">Run</th>
                  {['Recall@10', 'MRR', 'nDCG@10', 'Faithfulness'].map((h) => (
                    <th key={h} className="px-3 py-2 text-right font-medium">
                      {h}
                    </th>
                  ))}
                  <th className="px-3 py-2 text-right font-medium">p50 search</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-surface">
                {runs.data.map((r) => (
                  <tr key={r.id} className="hover:bg-surface-muted">
                    <td className="px-3 py-2">
                      <input type="checkbox" aria-label={`Compare ${r.name}`} checked={picked.includes(r.id)} onChange={() => toggle(r.id)} disabled={r.status !== 'ready'} className="accent-[var(--primary)]" />
                    </td>
                    <td className="px-3 py-2">
                      <Link to={`/evaluation/runs/${r.id}`} className="font-medium text-text hover:text-primary">
                        {r.name}
                      </Link>
                      <p className="text-caption text-subtle">
                        {configLabel(r)} · {r.items_evaluated || '…'} questions · {timeAgo(r.created_at)}
                      </p>
                      {r.status === 'failed' && <p className="text-caption text-error">{r.error_message}</p>}
                    </td>
                    {r.status === 'ready' ? (
                      <>
                        {['recall@10', 'mrr', 'ndcg@10', 'faithfulness'].map((k) => (
                          <td key={k} className="px-3 py-2 text-right text-text tabular-nums">
                            {fmt(r.metrics[k])}
                          </td>
                        ))}
                        <td className="px-3 py-2 text-right text-muted tabular-nums">{fmt(r.metrics.latency_search_p50_ms, 0)} ms</td>
                      </>
                    ) : (
                      <td colSpan={5} className="px-3 py-2 text-right text-muted">
                        {r.status === 'failed' ? (
                          'Failed'
                        ) : (
                          <span className="inline-flex items-center gap-1.5">
                            <Loader2 className="size-3.5 animate-spin" aria-hidden /> {r.status === 'queued' ? 'Queued' : 'Running'}
                          </span>
                        )}
                      </td>
                    )}
                    <td className="px-2">
                      <Button variant="ghost" size="icon-sm" aria-label={`Delete ${r.name}`} onClick={() => remove.mutate(r.id)}>
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

// --- compare --------------------------------------------------------------------------------------

function CompareView() {
  const [params] = useSearchParams()
  const ids = (params.get('runs') ?? '').split(',').filter(Boolean)
  const runs = useQuery({
    queryKey: ['evaluation', 'compare', ids],
    queryFn: () => Promise.all(ids.map((id) => evaluationApi.run(id))),
    enabled: ids.length > 0,
  })
  if (ids.length < 2)
    return <EmptyState icon={FlaskConical} title="Pick runs to compare" description="On the Runs tab, tick 2–4 finished runs and press Compare." />
  if (runs.isPending) return <Skeleton className="h-64 w-full" />
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
  const list = runs.data
  const sameDataset = new Set(list.map((r) => r.dataset_id)).size === 1
  const hasRag = list.some((r) => r.kind === 'rag')
  const metrics = [...RETRIEVAL_METRICS, ...(hasRag ? RAG_METRICS : [])]
  const base = list[0]
  // Per question: where the runs disagree on finding the expected evidence (Recall@10).
  const questions = base.per_item.map((item) => ({
    question: item.question,
    values: list.map((r) => r.per_item.find((p) => p.item_id === item.item_id)?.metrics['recall@10'] ?? null),
  }))
  const disagreements = questions.filter((q) => new Set(q.values.map((v) => (v ?? 0) > 0)).size > 1)
  return (
    <div className="space-y-6">
      {!sameDataset && (
        <p className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-small text-warning">
          These runs used different datasets, so their numbers aren’t directly comparable.
        </p>
      )}
      <Card className="p-4">
        <h2 className="mb-1 text-small font-semibold text-text">Quality (0–1, higher is better)</h2>
        <p className="mb-3 text-caption text-subtle">Hover a bar for its value; all values are in the table below.</p>
        <MetricBars metrics={metrics} runs={list.map((r) => ({ id: r.id, name: r.name, values: r.metrics }))} />
      </Card>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[640px] text-small">
          <thead className="bg-surface-muted text-left text-caption text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Metric</th>
              {list.map((r, i) => (
                <th key={r.id} className="px-3 py-2 text-right font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden className="size-2.5 rounded-sm" style={{ background: SERIES[i] }} />
                    {r.name}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {[
              ...metrics,
              { key: 'latency_search_p50_ms', label: 'Search p50 (ms)' },
              { key: 'latency_total_p95_ms', label: 'Total p95 (ms)' },
              ...(hasRag
                ? [
                    { key: 'tokens_input', label: 'Input tokens' },
                    { key: 'tokens_output', label: 'Output tokens' },
                    { key: 'cost_usd', label: 'Cost (USD)' },
                  ]
                : []),
            ].map((m) => (
              <tr key={m.key}>
                <td className="px-3 py-2 text-muted">
                  {METRIC_HELP[m.key] ? (
                    <Tooltip content={METRIC_HELP[m.key]}>
                      <span className="underline decoration-dotted underline-offset-2" tabIndex={0}>
                        {m.label}
                      </span>
                    </Tooltip>
                  ) : (
                    m.label
                  )}
                </td>
                {list.map((r, i) => {
                  const value = r.metrics[m.key]
                  const delta = i > 0 && typeof value === 'number' && typeof base.metrics[m.key] === 'number' ? value - (base.metrics[m.key] as number) : null
                  const isLatency = m.key.includes('latency') || m.key.includes('tokens') || m.key.includes('cost')
                  return (
                    <td key={r.id} className="px-3 py-2 text-right text-text tabular-nums">
                      {fmt(value, isLatency ? (m.key === 'cost_usd' ? 4 : 0) : 3)}
                      {delta !== null && Math.abs(delta) > 1e-9 && !isLatency && (
                        <span className={cn('ml-1.5 text-caption', delta > 0 ? 'text-success' : 'text-error')}>
                          {delta > 0 ? '+' : ''}
                          {delta.toFixed(3)}
                        </span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-caption text-subtle">
        Differences are relative to “{base.name}”. With {base.items_evaluated} questions, small differences are noise —
        look for consistent gaps, and at the questions below.
      </p>
      <div>
        <h2 className="mb-2 text-small font-semibold text-text">Questions where the runs disagree ({disagreements.length})</h2>
        {disagreements.length === 0 ? (
          <p className="text-small text-muted">Every run found the expected evidence for the same questions.</p>
        ) : (
          <ul className="space-y-1.5">
            {disagreements.map((q) => (
              <li key={q.question} className="flex flex-wrap items-center gap-2 text-small">
                <span className="min-w-0 flex-1 text-text">{q.question}</span>
                {q.values.map((v, i) => (
                  <Badge key={i} tone={(v ?? 0) > 0 ? 'success' : 'error'}>
                    <span aria-hidden className="size-2 rounded-sm" style={{ background: SERIES[i] }} />
                    {(v ?? 0) > 0 ? 'found' : 'missed'}
                  </Badge>
                ))}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// --- datasets -------------------------------------------------------------------------------------

function AddQuestion({ datasetId }: { datasetId: string }) {
  const [question, setQuestion] = useState('')
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<{ id: string; label: string }[]>([])
  const q = useDebounced(query.trim(), 300)
  const results = useQuery({
    queryKey: ['evaluation', 'passage-search', q],
    queryFn: () => searchApi.search({ query: q, mode: 'hybrid', limit: 8, rerank: false }),
    enabled: q.length > 2,
  })
  const add = useEvalAction(
    () => evaluationApi.addItem(datasetId, { question, chunk_ids: chosen.map((c) => c.id) }),
    'Question added',
  )
  return (
    <Card className="space-y-3 p-4">
      <h3 className="text-small font-semibold text-text">Add a question</h3>
      <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="The question" aria-label="Question" />
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-subtle" aria-hidden />
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search for the passages that answer it…" aria-label="Search passages" className="pl-8" />
      </div>
      {results.isFetching && (
        <p className="flex items-center gap-1.5 text-caption text-muted">
          <Loader2 className="size-3.5 animate-spin" aria-hidden /> Searching…
        </p>
      )}
      {results.data && (
        <ul className="max-h-64 space-y-1 overflow-y-auto">
          {results.data.results.map((r) => {
            const on = chosen.some((c) => c.id === r.chunk_id)
            return (
              <li key={r.chunk_id}>
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    setChosen((c) =>
                      on ? c.filter((x) => x.id !== r.chunk_id) : [...c, { id: r.chunk_id, label: `${r.document.title}, p. ${r.page_start}` }],
                    )
                  }
                  className={cn('w-full rounded-md border p-2 text-left text-caption', on ? 'border-primary bg-primary-soft/40' : 'border-border hover:bg-surface-muted')}
                >
                  <span className="font-medium text-text">
                    {r.document.title}, p. {r.page_start}
                  </span>
                  <span className="mt-0.5 line-clamp-2 block text-muted">{r.text}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {chosen.length > 0 && (
        <p className="text-caption text-muted">Expected evidence: {chosen.map((c) => c.label).join('; ')}</p>
      )}
      <Button onClick={() => add.mutate(undefined, { onSuccess: () => (setQuestion(''), setChosen([]), setQuery('')) })} disabled={question.trim().length < 5 || !chosen.length} loading={add.isPending}>
        <Plus className="size-4" aria-hidden /> Add question
      </Button>
    </Card>
  )
}

function DatasetsView() {
  const datasets = useDatasets()
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [count, setCount] = useState(10)
  const current = selected ?? datasets.data?.[0]?.id ?? null
  const dataset = datasets.data?.find((d) => d.id === current)
  const items = useItems(current)
  const create = useEvalAction(() => evaluationApi.createDataset({ name }), 'Dataset created')
  const generate = useEvalAction(() => evaluationApi.generate(current!, count))
  const accept = useEvalAction((id: string) => evaluationApi.updateItem(id, { status: 'verified' }))
  const remove = useEvalAction((id: string) => evaluationApi.deleteItem(id))
  const unverified = useMemo(() => items.data?.filter((i) => i.status === 'unverified') ?? [], [items.data])
  if (datasets.isPending) return <Skeleton className="h-48 w-full" />
  if (datasets.isError) return <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
  return (
    <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
      <div className="space-y-3">
        <ul className="space-y-1">
          {datasets.data.map((d) => (
            <li key={d.id}>
              <button
                type="button"
                onClick={() => setSelected(d.id)}
                className={cn('w-full rounded-md px-3 py-2 text-left', current === d.id ? 'bg-primary-soft' : 'hover:bg-surface-muted')}
              >
                <span className="block text-small font-medium text-text">{d.name}</span>
                <span className="text-caption text-subtle">
                  {d.verified} verified{d.unverified ? ` · ${d.unverified} to review` : ''} · {d.runs} runs
                </span>
              </button>
            </li>
          ))}
        </ul>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) create.mutate(undefined, { onSuccess: () => setName('') })
          }}
        >
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="New dataset name" aria-label="New dataset name" />
          <Button type="submit" variant="secondary" size="icon" aria-label="Create dataset" disabled={!name.trim()}>
            <Plus className="size-4" aria-hidden />
          </Button>
        </form>
      </div>
      {!dataset ? (
        <EmptyState icon={FlaskConical} title="No datasets yet" description="Create one, then add questions with the passages that answer them — or let the model draft questions for you to check." />
      ) : (
        <div className="space-y-6">
          <AddQuestion datasetId={dataset.id} />
          <Card className="space-y-2 p-4">
            <h3 className="text-small font-semibold text-text">Draft questions from your papers</h3>
            <p className="text-caption text-subtle">
              The model writes one question per sampled passage; that passage becomes the expected evidence. Drafts don’t
              count until you accept them — a model-written question can be vague or answerable from elsewhere.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input type="number" min={1} max={30} value={count} onChange={(e) => setCount(Number(e.target.value))} aria-label="Number of questions" className="h-9 w-20 rounded-md border border-border bg-surface px-2 text-small text-text" />
              <Button variant="secondary" onClick={() => generate.mutate(undefined)} loading={generate.isPending || dataset.generation.status === 'running'}>
                <Sparkles className="size-4" aria-hidden /> Draft questions
              </Button>
              {dataset.generation.status === 'done' && (
                <span className="text-caption text-subtle">
                  Last draft: {dataset.generation.created} written{dataset.generation.skipped ? `, ${dataset.generation.skipped} unusable replies skipped` : ''}.
                </span>
              )}
              {dataset.generation.status === 'failed' && <span className="text-caption text-error">{dataset.generation.error}</span>}
            </div>
          </Card>
          {items.isPending ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <div>
              <h3 className="mb-2 text-small font-semibold text-text">
                Questions ({items.data?.length ?? 0}){unverified.length ? ` · ${unverified.length} to review` : ''}
              </h3>
              <ul className="space-y-2">
                {items.data?.map((item) => (
                  <li key={item.id} className={cn('rounded-md border p-3', item.status === 'unverified' ? 'border-warning/40 bg-warning-soft/30' : 'border-border')}>
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-small text-text">{item.question}</p>
                        <p className="mt-0.5 text-caption text-subtle">
                          {item.expected.map((e) => `${e.title}, p. ${e.page}`).join('; ')}
                        </p>
                        <details className="mt-1 text-caption">
                          <summary className="cursor-pointer text-subtle">Expected passage</summary>
                          <p className="mt-1 text-muted">{item.expected[0]?.quote}</p>
                        </details>
                      </div>
                      <Badge tone={item.source === 'generated' ? 'info' : 'neutral'}>{item.source}</Badge>
                      {item.status === 'unverified' && (
                        <Button size="sm" variant="secondary" onClick={() => accept.mutate(item.id)} aria-label={`Accept: ${item.question}`}>
                          <Check className="size-3.5" aria-hidden /> Accept
                        </Button>
                      )}
                      <Button variant="ghost" size="icon-sm" aria-label={`Delete: ${item.question}`} onClick={() => remove.mutate(item.id)}>
                        {item.status === 'unverified' ? <X className="size-4" aria-hidden /> : <Trash2 className="size-4" aria-hidden />}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function EvaluationPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') ?? 'runs'
  return (
    <PageContainer width="wide">
      <PageHeader
        title="Evaluation"
        description="For technical users: measure how well search finds the right passages and how faithful answers are, and compare configurations on your own questions."
      />
      <Tabs value={view} onValueChange={(v) => setParams({ view: v })}>
        <TabsList className="mb-6">
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="compare">Compare</TabsTrigger>
          <TabsTrigger value="datasets">Datasets</TabsTrigger>
        </TabsList>
        <TabsContent value="runs">{view === 'runs' && <RunsView />}</TabsContent>
        <TabsContent value="compare">{view === 'compare' && <CompareView />}</TabsContent>
        <TabsContent value="datasets">{view === 'datasets' && <DatasetsView />}</TabsContent>
      </Tabs>
    </PageContainer>
  )
}
