import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'
import { DailyColumns } from '@/components/usage/DailyColumns'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { usageApi } from '@/services/api'
import type { UsageGroup, UsageSummary } from '@/types/api'

const FEATURES: Record<string, string> = {
  chat: 'Research chat',
  summary: 'Paper summaries',
  comparison: 'Comparisons',
  report: 'Reviews & research',
  project: 'Research projects',
  topics: 'Topic names',
  evaluation: 'Evaluation',
  other: 'Other',
}

const int = (n: number) => n.toLocaleString()
const ms = (v: number | null | undefined) =>
  v === null || v === undefined ? '–' : v >= 10_000 ? `${(v / 1000).toFixed(0)} s` : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`
const usd = (v: number) => (v === 0 ? '$0' : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`)

/** Every day of the window, oldest first, with 0 for days without calls. */
function fillDays(summary: UsageSummary) {
  const byDay = new Map(summary.by_day.map((d) => [d.day, d.calls]))
  const out = []
  const today = new Date()
  for (let i = summary.days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i))
    const day = d.toISOString().slice(0, 10)
    out.push({ day, value: byDay.get(day) ?? 0 })
  }
  return out
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border bg-surface p-3">
      <p className="text-caption text-muted">{label}</p>
      <p className="mt-0.5 text-h3 text-text tabular-nums">{value}</p>
      {hint && <p className="text-caption text-subtle">{hint}</p>}
    </div>
  )
}

function GroupTable({ rows, by }: { rows: UsageGroup[]; by: 'feature' | 'model' }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[640px] text-small">
        <thead className="bg-surface-muted text-left text-caption text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">{by === 'feature' ? 'Feature' : 'Model'}</th>
            {['Calls', 'Input tokens', 'Output tokens', 'Cost', 'Latency p50', 'p95', 'First token p50'].map((h) => (
              <th key={h} className="px-3 py-2 text-right font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border bg-surface">
          {rows.map((r) => (
            <tr key={r[by]}>
              <td className="px-3 py-2 text-text">
                {by === 'feature' ? (FEATURES[r.feature!] ?? r.feature) : <span className="font-mono text-caption">{r.model}</span>}
                {r.errors > 0 && <span className="ml-2 text-caption text-error">{r.errors} failed</span>}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{int(r.calls)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{int(r.input_tokens)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{int(r.output_tokens)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{usd(r.cost_usd)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{ms(r.latency_p50_ms)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{ms(r.latency_p95_ms)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{ms(r.first_token_p50_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Usage({ days }: { days: number }) {
  const usage = useQuery({ queryKey: ['usage', days], queryFn: () => usageApi.summary(days) })
  if (usage.isPending) return <Skeleton className="h-64 w-full" />
  if (usage.isError) return <ErrorState error={usage.error} onRetry={() => usage.refetch()} />
  const u = usage.data
  const t = u.totals
  const price = u.pricing.current_model
  if (t.calls === 0)
    return (
      <EmptyState
        icon={Gauge}
        className="rounded-lg border border-dashed border-border"
        title="No language-model calls yet"
        description="Ask a question, summarize a paper or write a review — each call's tokens, time and cost appear here."
      />
    )
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Model calls" value={int(t.calls)} hint={t.errors ? `${t.errors} failed` : undefined} />
        <Stat label="Tokens in / out" value={`${int(t.input_tokens)} / ${int(t.output_tokens)}`} hint={t.estimated_calls ? `${t.estimated_calls} estimated (stopped early)` : undefined} />
        <Stat label="Cost" value={usd(t.cost_usd)} hint={price.input || price.output ? `${price.model}: $${price.input} / $${price.output} per M tokens` : `${price.model || 'Local model'}: no per-token cost`} />
        <Stat label="Call time p50 / p95" value={`${ms(t.latency_p50_ms)} / ${ms(t.latency_p95_ms)}`} />
      </div>
      <Card className="p-4">
        <h2 className="mb-2 text-small font-semibold text-text">Model calls per day</h2>
        <div className="max-w-3xl">
          <DailyColumns days={fillDays(u)} label="Model calls" format={(v) => int(Math.round(v))} />
        </div>
        <details className="mt-2 text-caption">
          <summary className="cursor-pointer text-subtle">Daily numbers</summary>
          <table className="mt-2 w-full max-w-lg">
            <thead className="text-left text-muted">
              <tr>
                <th className="py-1 font-medium">Day</th>
                <th className="py-1 text-right font-medium">Calls</th>
                <th className="py-1 text-right font-medium">Tokens in</th>
                <th className="py-1 text-right font-medium">Tokens out</th>
                <th className="py-1 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody className="text-text">
              {u.by_day.map((d) => (
                <tr key={d.day}>
                  <td className="py-0.5">{d.day}</td>
                  <td className="py-0.5 text-right tabular-nums">{int(d.calls)}</td>
                  <td className="py-0.5 text-right tabular-nums">{int(d.input_tokens)}</td>
                  <td className="py-0.5 text-right tabular-nums">{int(d.output_tokens)}</td>
                  <td className="py-0.5 text-right tabular-nums">{usd(d.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </Card>
      <section>
        <h2 className="mb-2 text-small font-semibold text-text">By feature</h2>
        <GroupTable rows={u.by_feature} by="feature" />
      </section>
      <section>
        <h2 className="mb-2 text-small font-semibold text-text">By model</h2>
        <GroupTable rows={u.by_model} by="model" />
        <p className="mt-2 text-caption text-subtle">
          Cost is stored with each call, priced when it was made. Set prices with <code>LLM_PRICES</code> (per model,
          USD per million input / output tokens) or <code>LLM_PRICE_INPUT_PER_MILLION</code> /{' '}
          <code>LLM_PRICE_OUTPUT_PER_MILLION</code>.
        </p>
      </section>
    </div>
  )
}

function Performance() {
  const perf = useQuery({ queryKey: ['usage', 'performance'], queryFn: usageApi.performance, refetchInterval: 15_000 })
  if (perf.isPending) return <Skeleton className="h-40 w-full" />
  if (perf.isError) return <ErrorState error={perf.error} onRetry={() => perf.refetch()} />
  const p = perf.data
  return (
    <div className="space-y-6">
      <p className="text-small text-muted">
        This server process, since it started {timeAgo(p.since)} — for every user. Percentiles are estimated from
        histogram buckets.
      </p>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[520px] text-small">
          <thead className="bg-surface-muted text-left text-caption text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Stage</th>
              {['Count', 'p50', 'p95', 'Mean'].map((h) => (
                <th key={h} className="px-3 py-2 text-right font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {p.stages.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-3 text-muted">
                  Nothing measured yet.
                </td>
              </tr>
            )}
            {p.stages.map((s) => (
              <tr key={s.key}>
                <td className="px-3 py-2 text-text">{s.label}</td>
                <td className="px-3 py-2 text-right tabular-nums">{int(s.count)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{ms(s.p50_ms)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{ms(s.p95_ms)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{ms(s.mean_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section>
        <h2 className="mb-2 text-small font-semibold text-text">Caches</h2>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[520px] text-small">
            <thead className="bg-surface-muted text-left text-caption text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Cache</th>
                {['Hit rate', 'Hits (here / shared)', 'Misses', 'Entries'].map((h) => (
                  <th key={h} className="px-3 py-2 text-right font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {p.caches.map((c) => (
                <tr key={c.name}>
                  <td className="px-3 py-2 text-text">
                    {c.name === 'query_embeddings' ? 'Query embeddings' : c.name === 'rerank_scores' ? 'Reranker scores' : c.name}
                    <span className="ml-2 text-caption text-subtle">{c.shared ? 'process + Redis' : 'this process'}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{c.hit_rate === null ? '–' : `${Math.round(c.hit_rate * 100)}%`}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {int(c.local_hits)} / {int(c.shared_hits)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{int(c.misses)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {int(c.entries)} / {int(c.max_entries)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-caption text-subtle">
          Answers to near-identical first questions are also reused when the same passages are found (shown on the
          answer, with “Answer again”). Prometheus metrics: <code>/metrics</code>.
        </p>
      </section>
    </div>
  )
}

export function UsagePage() {
  const [days, setDays] = useState(30)
  return (
    <PageContainer width="wide">
      <PageHeader
        title="Usage & performance"
        description="Language-model calls, tokens and cost by feature, and how long each stage takes."
        actions={
          <div className="flex rounded-md border border-border bg-surface p-0.5" role="group" aria-label="Period">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                type="button"
                aria-pressed={days === d}
                onClick={() => setDays(d)}
                className={cn('rounded px-2.5 py-1 text-small', days === d ? 'bg-primary-soft text-primary' : 'text-muted hover:text-text')}
              >
                {d} days
              </button>
            ))}
          </div>
        }
      />
      <div className="space-y-10">
        <Usage days={days} />
        <section>
          <h2 className="mb-3 text-h3 text-text">Performance</h2>
          <Performance />
        </section>
      </div>
    </PageContainer>
  )
}
