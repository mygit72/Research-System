import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { FileText, Loader2, X } from 'lucide-react'
import { PaperPicker } from '@/components/documents/PaperPicker'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { useCollections } from '@/hooks/useOrganization'
import { useCreateReport, useReports } from '@/hooks/useReports'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { REPORT_KINDS } from '@/lib/reports'
import type { DocumentSummary, ReportDepth, ReportKind, ReportRequest } from '@/types/api'

const KINDS = Object.keys(REPORT_KINDS) as ReportKind[]
const DEPTHS: { value: ReportDepth; label: string; help: string }[] = [
  { value: 'brief', label: 'Brief', help: 'up to 6 papers' },
  { value: 'standard', label: 'Standard', help: 'up to 10 papers' },
  { value: 'detailed', label: 'Detailed', help: 'up to 16 papers' },
]
type Scope = 'library' | 'collection' | 'papers'

const STATUS_TONE = { queued: 'neutral', running: 'info', ready: 'success', failed: 'error' } as const
const STATUS_LABEL = { queued: 'Queued', running: 'Writing…', ready: 'Ready', failed: 'Failed' } as const

function NewReport() {
  const [params, setParams] = useSearchParams()
  const kind = (KINDS.includes(params.get('kind') as ReportKind) ? params.get('kind') : 'review') as ReportKind
  const [text, setText] = useState('')
  const [scope, setScope] = useState<Scope>(params.get('collection') ? 'collection' : 'library')
  const [collectionId, setCollectionId] = useState(params.get('collection') ?? '')
  const [papers, setPapers] = useState<DocumentSummary[]>([])
  const [depth, setDepth] = useState<ReportDepth>('standard')
  const [maxSteps, setMaxSteps] = useState(16)
  const [minutes, setMinutes] = useState(15)
  const collections = useCollections()
  const create = useCreateReport()
  const navigate = useNavigate()
  const meta = REPORT_KINDS[kind]
  const isResearch = kind === 'deep_research'

  const missing =
    isResearch
      ? text.trim().split(/\s+/).length < 3 && 'Ask a question of at least a few words.'
      : scope === 'collection' && !collectionId
        ? 'Choose a collection.'
        : scope === 'papers' && papers.length < (kind === 'gaps' ? 1 : 2)
          ? `Choose at least ${kind === 'gaps' ? 1 : 2} papers.`
          : scope === 'library' && !text.trim()
            ? 'Describe the topic, or choose a collection or papers.'
            : null

  const submit = () => {
    const body: ReportRequest = {
      ...(isResearch ? { question: text.trim() } : { topic: text.trim() }),
      ...(scope === 'collection' ? { collection_id: collectionId } : {}),
      ...(scope === 'papers' ? { document_ids: papers.map((p) => p.id) } : {}),
      ...(isResearch ? { max_steps: maxSteps, timeout_seconds: minutes * 60 } : { depth }),
    }
    create.mutate({ kind, body }, { onSuccess: (report) => navigate(`/reviews/${report.id}`) })
  }

  return (
    <section className="rounded-lg border border-border bg-surface p-5 shadow-sm" aria-labelledby="new-report">
      <h2 id="new-report" className="sr-only">
        New report
      </h2>
      <div role="tablist" aria-label="Report type" className="flex flex-wrap gap-1 rounded-md bg-surface-muted p-1">
        {KINDS.map((k) => {
          const Icon = REPORT_KINDS[k].icon
          return (
            <button
              key={k}
              role="tab"
              type="button"
              aria-selected={kind === k}
              onClick={() => setParams((p) => (p.set('kind', k), p), { replace: true })}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-small font-medium transition-colors',
                kind === k ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-text',
              )}
            >
              <Icon className="size-4" aria-hidden /> {REPORT_KINDS[k].label}
            </button>
          )
        })}
      </div>
      <p className="mt-3 text-small text-muted">{meta.description}</p>

      <div className="mt-4 space-y-4">
        <label className="block">
          <span className="text-small font-medium text-text">{isResearch ? 'Research question' : 'Topic'}</span>
          {!isResearch && <span className="ml-1 text-caption text-subtle">(optional when you choose papers)</span>}
          {isResearch ? (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={2}
              placeholder="e.g. What are the current approaches to evaluating retrieval-augmented generation?"
              className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-small text-text placeholder:text-subtle focus:border-primary focus:outline-none"
            />
          ) : (
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="e.g. parameter-efficient fine-tuning"
              className="mt-1"
            />
          )}
        </label>

        <fieldset>
          <legend className="text-small font-medium text-text">Papers</legend>
          <div className="mt-1.5 flex flex-wrap gap-4 text-small text-text">
            {(
              [
                ['library', isResearch ? 'All my papers' : 'Find them from the topic'],
                ['collection', 'A collection'],
                ['papers', 'Choose papers'],
              ] as const
            ).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="scope"
                  checked={scope === value}
                  onChange={() => setScope(value)}
                  className="accent-[var(--primary)]"
                />
                {label}
              </label>
            ))}
          </div>
          {scope === 'collection' && (
            <select
              aria-label="Collection"
              value={collectionId}
              onChange={(e) => setCollectionId(e.target.value)}
              className="mt-2 h-9 w-full max-w-sm rounded-md border border-border bg-surface px-2 text-small text-text"
            >
              <option value="">Choose a collection…</option>
              {collections.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.paper_count})
                </option>
              ))}
            </select>
          )}
          {scope === 'papers' && (
            <div className="mt-2 max-w-xl space-y-2">
              <PaperPicker
                picked={papers.map((p) => p.id)}
                onAdd={(doc) => setPapers((list) => [...list, doc].slice(0, 30))}
                reason={(doc) => (doc.index_status !== 'indexed' ? 'Not searchable yet' : null)}
              />
              <ul className="flex flex-wrap gap-1.5">
                {papers.map((p) => (
                  <li key={p.id}>
                    <Badge className="max-w-xs">
                      <span className="truncate">{p.title}</span>
                      <button
                        type="button"
                        aria-label={`Remove ${p.title}`}
                        onClick={() => setPapers((list) => list.filter((x) => x.id !== p.id))}
                      >
                        <X className="size-3" aria-hidden />
                      </button>
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </fieldset>

        {isResearch ? (
          <details className="text-small">
            <summary className="cursor-pointer text-muted">Limits</summary>
            <div className="mt-2 flex flex-wrap gap-4">
              <label className="flex flex-col gap-1 text-caption text-muted">
                Maximum steps
                <input
                  type="number"
                  min={3}
                  max={40}
                  value={maxSteps}
                  onChange={(e) => setMaxSteps(Number(e.target.value))}
                  className="h-9 w-24 rounded-md border border-border bg-surface px-2 text-small text-text"
                />
              </label>
              <label className="flex flex-col gap-1 text-caption text-muted">
                Time limit (minutes)
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={minutes}
                  onChange={(e) => setMinutes(Number(e.target.value))}
                  className="h-9 w-24 rounded-md border border-border bg-surface px-2 text-small text-text"
                />
              </label>
            </div>
            <p className="mt-2 text-caption text-subtle">
              The assistant only searches your papers (read-only) and stops at whichever limit comes first.
            </p>
          </details>
        ) : (
          <fieldset>
            <legend className="text-small font-medium text-text">Depth</legend>
            <div className="mt-1.5 flex flex-wrap gap-4 text-small text-text">
              {DEPTHS.map((d) => (
                <label key={d.value} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="depth"
                    checked={depth === d.value}
                    onChange={() => setDepth(d.value)}
                    className="accent-[var(--primary)]"
                  />
                  {d.label} <span className="text-caption text-subtle">{d.help}</span>
                </label>
              ))}
            </div>
          </fieldset>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={submit} disabled={!!missing} loading={create.isPending}>
            {meta.action}
          </Button>
          <span className="text-caption text-subtle">
            {missing ||
              'Runs in the background. Papers without a summary are summarized first, so the first report can take several minutes on a local model.'}
          </span>
        </div>
      </div>
    </section>
  )
}

export function ReportsPage() {
  const reports = useReports()
  return (
    <PageContainer>
      <PageHeader
        title="Reviews & Research"
        description="Literature reviews, research gaps, disagreements and multi-step research — written from your papers, with every statement cited and checked."
      />
      <NewReport />
      <h2 className="mt-10 mb-3 text-h3 text-text">Your reports</h2>
      {reports.isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : reports.isError ? (
        <ErrorState error={reports.error} onRetry={() => reports.refetch()} />
      ) : reports.data.length === 0 ? (
        <EmptyState
          icon={FileText}
          className="rounded-lg border border-dashed border-border"
          title="No reports yet"
          description="Start one above. You can edit a finished report and export it to Markdown, Word or PDF."
        />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {reports.data.map((r) => {
            const Icon = REPORT_KINDS[r.kind].icon
            return (
              <li key={r.id}>
                <Link to={`/reviews/${r.id}`} className="flex items-start gap-3 px-4 py-3 hover:bg-surface-muted">
                  <Icon className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-text">{r.title}</p>
                    <p className="text-caption text-subtle">
                      {REPORT_KINDS[r.kind].label} · {r.document_ids.length ? `${r.document_ids.length} papers · ` : ''}
                      {timeAgo(r.created_at)}
                      {r.edited_at ? ' · edited' : ''}
                    </p>
                  </div>
                  <Badge tone={STATUS_TONE[r.status]}>
                    {r.status === 'running' && <Loader2 className="size-3 animate-spin" aria-hidden />}
                    {STATUS_LABEL[r.status]}
                  </Badge>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </PageContainer>
  )
}
