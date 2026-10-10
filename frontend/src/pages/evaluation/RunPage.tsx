import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Check, X } from 'lucide-react'
import { MetricBars } from '@/components/evaluation/MetricBars'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { ErrorState, ProgressBar, Skeleton } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { useRun } from '@/hooks/useEvaluation'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { METRIC_HELP, RAG_METRICS, RETRIEVAL_METRICS, configLabel, fmt } from '@/lib/evaluation'
import type { EvalRun } from '@/types/api'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border bg-surface p-3">
      <p className="text-caption text-muted">{label}</p>
      <p className="mt-0.5 text-h3 text-text tabular-nums">{value}</p>
      {hint && <p className="text-caption text-subtle">{hint}</p>}
    </div>
  )
}

function Question({ item, rag }: { item: EvalRun['per_item'][number]; rag: boolean }) {
  const [open, setOpen] = useState(false)
  const found = (item.metrics['recall@10'] ?? 0) > 0
  return (
    <li className="rounded-md border border-border bg-surface">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-start gap-3 p-3 text-left">
        <Badge tone={found ? 'success' : 'error'}>
          {found ? <Check className="size-3" aria-hidden /> : <X className="size-3" aria-hidden />}
          {found ? 'found' : 'missed'}
        </Badge>
        <span className="min-w-0 flex-1 text-small text-text">{item.question}</span>
        <span className="shrink-0 text-caption text-muted tabular-nums">
          RR {fmt(item.metrics.mrr, 2)}
          {rag && ` · faithful ${fmt(item.metrics.faithfulness, 2)}`}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-border p-3 text-caption">
          <div>
            <p className="mb-1 font-medium text-muted">Top passages</p>
            <ol className="space-y-0.5">
              {item.top.map((t, i) => (
                <li key={i} className={cn('flex gap-2', t.relevant ? 'text-success' : 'text-muted')}>
                  <span className="w-4 text-right tabular-nums">{i + 1}.</span>
                  <span>
                    {t.title}, p. {t.page}
                    {t.relevant && ' — expected evidence'}
                  </span>
                </li>
              ))}
            </ol>
          </div>
          {item.answer && (
            <div>
              <p className="mb-1 font-medium text-muted">Answer</p>
              <p className="whitespace-pre-wrap text-text">{item.answer}</p>
            </div>
          )}
          <p className="text-subtle">
            Latency: {Object.entries(item.latency_ms).map(([k, v]) => `${k} ${Math.round(v)} ms`).join(' · ')}
          </p>
        </div>
      )}
    </li>
  )
}

export function RunPage() {
  const { id = '' } = useParams()
  const run = useRun(id)
  if (run.isPending)
    return (
      <PageContainer width="wide">
        <Skeleton className="h-64 w-full" />
      </PageContainer>
    )
  if (run.isError)
    return (
      <PageContainer width="wide">
        <ErrorState error={run.error} onRetry={() => run.refetch()} />
      </PageContainer>
    )
  const r = run.data
  const m = r.metrics
  const rag = r.kind === 'rag'
  const metrics = [...RETRIEVAL_METRICS, ...(rag ? RAG_METRICS : [])]
  return (
    <PageContainer width="wide">
      <Link to="/evaluation" className="mb-4 inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-4" aria-hidden /> Evaluation
      </Link>
      <PageHeader title={r.name} description={`${configLabel(r)} · ${timeAgo(r.created_at)}`} />
      {r.status !== 'ready' ? (
        r.status === 'failed' ? (
          <ErrorState error={new Error(r.error_message ?? 'The run failed')} />
        ) : (
          <Card className="space-y-2 p-4">
            <p className="text-small text-text">{r.progress?.detail ?? (r.status === 'queued' ? 'Waiting to start…' : 'Running…')}</p>
            <ProgressBar value={r.progress?.progress ?? 0} label="Run progress" />
          </Card>
        )
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Questions" value={String(r.items_evaluated)} />
            <Stat label="Search p50 / p95" value={`${fmt(m.latency_search_p50_ms, 0)} / ${fmt(m.latency_search_p95_ms, 0)} ms`} />
            <Stat label="Throughput" value={`${fmt(m.throughput_per_min, 1)} / min`} hint="questions, end to end" />
            <Stat
              label={rag ? 'Tokens in / out' : 'Total time'}
              value={rag ? `${m.tokens_input ?? 0} / ${m.tokens_output ?? 0}` : `${((r.latency_ms ?? 0) / 1000).toFixed(1)} s`}
              hint={rag ? `Cost $${fmt(m.cost_usd, 4)}` : undefined}
            />
          </div>
          <Card className="p-4">
            <h2 className="mb-1 text-small font-semibold text-text">Quality (0–1, higher is better)</h2>
            <MetricBars metrics={metrics} runs={[{ id: r.id, name: r.name, values: m }]} />
            <table className="mt-4 w-full text-small">
              <tbody className="divide-y divide-border">
                {metrics.map((x) => (
                  <tr key={x.key}>
                    <td className="py-1.5 text-muted">
                      {x.label}
                      <span className="block text-caption text-subtle">{METRIC_HELP[x.key]}</span>
                    </td>
                    <td className="py-1.5 text-right text-text tabular-nums">{fmt(m[x.key])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rag && (m.insufficient ?? 0) > 0 && (
              <p className="mt-3 text-caption text-muted">
                {Math.round((m.insufficient ?? 0) * r.items_evaluated)} of {r.items_evaluated} answers said the passages
                weren’t enough; they are left out of faithfulness, citation correctness and answer relevance.
              </p>
            )}
          </Card>
          <div>
            <h2 className="mb-2 text-small font-semibold text-text">Per question</h2>
            <ul className="space-y-2">
              {r.per_item.map((item) => (
                <Question key={item.item_id} item={item} rag={rag} />
              ))}
            </ul>
          </div>
          <details className="text-caption text-subtle">
            <summary className="cursor-pointer">Configuration snapshot</summary>
            <pre className="mt-2 overflow-x-auto rounded-md bg-surface-muted p-3 text-muted">{JSON.stringify(r.config, null, 2)}</pre>
          </details>
        </div>
      )}
    </PageContainer>
  )
}
