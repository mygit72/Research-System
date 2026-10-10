import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronDown,
  Download,
  Footprints,
  Loader2,
  Pencil,
  Search as SearchIcon,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { citationRenderer } from '@/components/chat/citations'
import { Markdown } from '@/components/chat/Markdown'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ErrorState, ProgressBar, Skeleton } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { PageContainer } from '@/components/ui/PageHeader'
import { Tooltip } from '@/components/ui/Tooltip'
import { useDeleteReport, useReport, useUpdateReport } from '@/hooks/useReports'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import {
  REPORT_KINDS,
  SECTION_DOT,
  SKIP_REASONS,
  STAGES,
  asEvidence,
  reportFilename,
  saveBlob,
  stageIndex,
} from '@/lib/reports'
import { reportsApi } from '@/services/api'
import type { Report, ReportSection } from '@/types/api'

type RenderCite = ReturnType<typeof citationRenderer>

const EDITABLE = new Set(['text', 'answer', 'chronology', 'open'])

function Cites({ numbers, renderCite }: { numbers: number[]; renderCite: RenderCite }) {
  if (!numbers.length) return null
  return <> {renderCite(numbers, numbers.map((n) => `[${n}]`).join(''), numbers.join('-'))}</>
}

function SectionStatus({ section }: { section: ReportSection }) {
  if (section.origin !== 'generated' && !section.edited)
    return <p className="text-caption text-subtle">{section.label}</p>
  const counts = section.claims.reduce<Record<string, number>>((acc, c) => ((acc[c.status] = (acc[c.status] ?? 0) + 1), acc), {})
  const detail = section.claims.length
    ? `${counts.supported ?? 0} of ${section.claims.length} sentences are directly supported by the passages they cite.`
    : 'Nothing to check.'
  return (
    <Tooltip content={section.edited ? 'You changed this text after it was checked.' : detail}>
      <span className="inline-flex items-center gap-1.5 text-caption text-muted" tabIndex={0}>
        <span className={cn('size-2 rounded-full', section.edited ? 'bg-subtle' : (SECTION_DOT[section.status] ?? 'bg-subtle'))} aria-hidden />
        {section.label}
      </span>
    </Tooltip>
  )
}

function TextSection({
  section,
  renderCite,
  editing,
  draft,
  onDraft,
}: {
  section: ReportSection
  renderCite: RenderCite
  editing: boolean
  draft: string | undefined
  onDraft: (text: string) => void
}) {
  if (editing && EDITABLE.has(section.kind))
    return (
      <textarea
        aria-label={`Text of “${section.title}”`}
        value={draft ?? section.text}
        onChange={(e) => onDraft(e.target.value)}
        rows={Math.min(14, Math.max(4, Math.ceil((draft ?? section.text).length / 90)))}
        className="w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-small leading-relaxed text-text focus:border-primary focus:outline-none"
      />
    )
  if (!section.text)
    return (
      <p className="text-small text-subtle italic">
        Your papers didn’t have enough evidence for this part, so nothing was written.
      </p>
    )
  return (
    <div className="text-body leading-relaxed text-text">
      <Markdown text={section.text} renderCite={renderCite} />
    </div>
  )
}

function ComparisonTable({ section, renderCite }: { section: ReportSection; renderCite: RenderCite }) {
  return (
    <div className="relative overflow-x-auto rounded-md border border-border">
      <table className="w-full min-w-[720px] text-small">
        <thead className="bg-surface-muted text-left text-caption text-muted">
          <tr>
            {['Paper', 'Approach', 'Datasets', 'Metrics', 'Key result'].map((h) => (
              <th key={h} className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border bg-surface align-top">
          {section.data?.rows?.map((row) => (
            <tr key={row.document.id}>
              <td className="px-3 py-2">
                <Link to={`/papers/${row.document.id}`} className="font-medium text-text hover:text-primary">
                  {row.document.title}
                </Link>
                {row.document.year && <span className="block text-caption text-subtle">{row.document.year}</span>}
              </td>
              <td className="px-3 py-2 text-muted">{row.approach || '—'}</td>
              <td className="px-3 py-2 text-muted">{row.datasets?.join(', ') || '–'}</td>
              <td className="px-3 py-2 text-muted">{row.metrics?.join(', ') || '–'}</td>
              <td className="px-3 py-2 text-text">
                {row.result}
                <Cites numbers={row.citations ?? []} renderCite={renderCite} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Chronology({ section }: { section: ReportSection }) {
  return (
    <ol className="space-y-1.5">
      {section.data?.rows?.map((row) => (
        <li key={row.document.id} className="flex gap-3 text-small">
          <span className="w-12 shrink-0 font-medium text-text tabular-nums">{row.year ?? '—'}</span>
          <span className="min-w-0 text-muted">
            <Link to={`/papers/${row.document.id}`} className="text-text hover:text-primary">
              {row.document.title}
            </Link>
            {row.proposes?.length ? ` — proposes ${row.proposes.join(', ')}` : ''}
          </span>
        </li>
      ))}
    </ol>
  )
}

function Disagreements({ section, renderCite }: { section: ReportSection; renderCite: RenderCite }) {
  const items = section.data?.items ?? []
  if (!items.length)
    return <p className="text-small text-muted">No statements in these papers look like they conflict.</p>
  return (
    <ul className="space-y-4">
      {items.map((item, i) => (
        <li key={i}>
          <Card className="p-4">
            <p className="flex flex-wrap items-center gap-2 text-small font-medium text-text">
              <AlertTriangle className="size-4 text-warning" aria-hidden /> {item.label} about {item.shared.join(', ')}
            </p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {[item.claim_a, item.claim_b].map((claim) => (
                <blockquote key={claim.document.id} className="rounded-md border-l-2 border-border-strong bg-surface-muted/50 p-3 text-small">
                  <Link to={`/papers/${claim.document.id}`} className="font-medium text-text hover:text-primary">
                    {claim.document.title}
                    {claim.document.year ? ` (${claim.document.year})` : ''}
                  </Link>
                  <p className="mt-1 text-muted">
                    {claim.text}
                    <Cites numbers={claim.citations} renderCite={renderCite} />
                  </p>
                </blockquote>
              ))}
            </div>
            {Object.keys(item.differences).length > 0 && (
              <dl className="mt-3 space-y-1 text-caption text-muted">
                {Object.entries(item.differences).map(([kind, diff]) => (
                  <div key={kind}>
                    <dt className="inline font-medium text-text">Different {kind}s: </dt>
                    <dd className="inline">
                      first uses {diff.a.join(', ') || 'none listed'}; second uses {diff.b.join(', ') || 'none listed'}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="mt-2 text-caption text-subtle">
              {item.note} Detected by {item.detector === 'nli' ? `the entailment model (contradiction ${item.score.toFixed(2)})` : 'opposite wording'}.
            </p>
          </Card>
        </li>
      ))}
    </ul>
  )
}

function Gaps({ section, renderCite }: { section: ReportSection; renderCite: RenderCite }) {
  const gaps = section.data?.gaps ?? []
  const directions = section.data?.directions ?? []
  if (!gaps.length) return <p className="text-small text-muted">No limitations or gaps were found in these papers.</p>
  return (
    <div className="space-y-6">
      {(['Stated by the authors', 'System-generated synthesis'] as const).map((origin) => {
        const items = gaps.filter((g) => g.origin === origin)
        if (!items.length) return null
        return (
          <div key={origin}>
            <h3 className="mb-2 flex items-center gap-2 text-small font-semibold text-text">
              <Badge tone={origin === 'Stated by the authors' ? 'success' : 'info'}>{origin}</Badge>
              <span className="font-normal text-caption text-subtle">
                {origin === 'Stated by the authors'
                  ? 'The papers’ own limitations and future work, checked against their text'
                  : 'Inferred by the system from the papers in this report — not the authors’ words'}
              </span>
            </h3>
            <ul className="space-y-2">
              {items.map((gap) => (
                <li key={gap.id} className="rounded-md border border-border p-3">
                  <p className="text-small font-medium text-text">
                    <span className="mr-1.5 text-caption text-subtle tabular-nums">{gap.id}</span>
                    {gap.title}
                  </p>
                  {gap.statements.length > 0 ? (
                    <ul className="mt-1.5 space-y-1">
                      {gap.statements.map((s, i) => (
                        <li key={i} className="text-small text-muted">
                          <span className="text-text">{s.document.title}:</span> {s.text}
                          <Cites numbers={s.citations} renderCite={renderCite} />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 text-small text-muted">{gap.text}</p>
                  )}
                  {gap.statements.length === 0 && gap.papers.length > 0 && (
                    <p className="mt-1 text-caption text-subtle">Papers: {gap.papers.map((p) => p.title).join('; ')}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )
      })}
      {directions.length > 0 && (
        <div>
          <h3 className="mb-2 flex items-center gap-2 text-small font-semibold text-text">
            Suggested directions <Badge tone="info">System-generated synthesis</Badge>
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-small text-text">
            {directions.map((d, i) => (
              <li key={i}>
                {d.text} <span className="text-caption text-subtle">(from {d.based_on.join(', ')})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Progress({ report }: { report: Report }) {
  const kind = report.kind
  const current = stageIndex(kind, report.progress?.stage)
  return (
    <Card className="p-5" aria-live="polite">
      <div className="flex items-center gap-2 text-small font-medium text-text">
        <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
        {report.status === 'queued' ? 'Waiting to start…' : (report.progress?.detail ?? 'Working…')}
      </div>
      <ProgressBar value={report.progress?.progress ?? 0} className="mt-3" label="Report progress" />
      <ol className="mt-4 space-y-1.5">
        {STAGES[kind].map((s, i) => (
          <li key={s.stage} className={cn('flex items-center gap-2 text-small', i <= current ? 'text-text' : 'text-subtle')}>
            {i < current ? (
              <Check className="size-4 text-success" aria-hidden />
            ) : i === current && report.status === 'running' ? (
              <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
            ) : (
              <span className="size-4 rounded-full border border-border" aria-hidden />
            )}
            {s.label}
          </li>
        ))}
      </ol>
      <p className="mt-4 text-caption text-subtle">You can leave this page; the report keeps being written.</p>
    </Card>
  )
}

function ResearchTrace({ report }: { report: Report }) {
  const steps = report.trace.steps ?? []
  if (!steps.length) return null
  const icon = (action: string) => (action === 'search' ? SearchIcon : Footprints)
  return (
    <details className="rounded-lg border border-border bg-surface p-4">
      <summary className="cursor-pointer text-small font-medium text-text">
        How the research was done ({steps.length} steps
        {report.trace.used ? ` · ${report.trace.used.tokens.toLocaleString()} tokens · ${Math.round(report.trace.used.seconds)} s` : ''})
      </summary>
      {report.trace.stopped && (
        <p className="mt-2 text-small text-warning">Stopped early: {report.trace.stopped}. The report covers what was done.</p>
      )}
      <ol className="mt-3 space-y-2">
        {steps.map((s) => {
          const Icon = icon(s.action)
          return (
            <li key={s.step} className="flex gap-2 text-small">
              <Icon className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
              <div className="min-w-0 text-muted">
                <span className="font-medium text-text capitalize">{s.action}</span>
                {s.action === 'plan' && s.subquestions && `: ${s.subquestions.length} sub-question${s.subquestions.length === 1 ? '' : 's'}`}
                {s.action === 'search' && `: “${s.query}” → kept ${s.kept} of ${s.found} passages`}
                {s.action === 'answer' && `: ${s.question} → ${s.status}`}
                {s.action === 'refine' && `: searched again for “${s.query}” (${s.new_passages} new passages)`}
                {s.action === 'synthesize' && ` the conclusion → ${s.status}`}
                {s.action === 'stopped' && `: ${s.reason}`}
              </div>
            </li>
          )
        })}
      </ol>
      <p className="mt-3 text-caption text-subtle">
        Tools: {report.trace.tools?.join('; ')} · Limits: {report.trace.limits?.max_steps} steps,{' '}
        {report.trace.limits?.token_budget.toLocaleString()} tokens, {Math.round((report.trace.limits?.timeout_seconds ?? 0) / 60)} min.
      </p>
    </details>
  )
}

export function ReportPage() {
  const { id = '' } = useParams()
  const report = useReport(id)
  const update = useUpdateReport(id)
  const remove = useDeleteReport()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const renderCite = useMemo(() => citationRenderer(report.data ? asEvidence(report.data) : [], null), [report.data])

  if (report.isPending)
    return (
      <PageContainer>
        <Skeleton className="h-10 w-80" />
        <Skeleton className="mt-6 h-72 w-full" />
      </PageContainer>
    )
  if (report.isError)
    return (
      <PageContainer>
        <ErrorState error={report.error} onRetry={() => report.refetch()} />
      </PageContainer>
    )
  const r = report.data
  const meta = REPORT_KINDS[r.kind]
  const Icon = meta.icon

  const save = () => {
    const sections = Object.entries(drafts).map(([key, text]) => ({ key, text }))
    update.mutate(
      { ...(title !== null && title !== r.title ? { title } : {}), ...(sections.length ? { sections } : {}) },
      {
        onSuccess: () => {
          setEditing(false)
          setDrafts({})
          setTitle(null)
        },
      },
    )
  }

  const download = async (format: 'md' | 'docx' | 'pdf') => {
    try {
      saveBlob(await reportsApi.export(r.id, format), reportFilename(r.title, format))
    } catch (error) {
      toast.error((error as Error).message)
    }
  }

  return (
    <PageContainer>
      <Link to="/reviews" className="inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-3.5" aria-hidden /> Reviews & Research
      </Link>
      <header className="mt-3 mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-small text-muted">
            <Icon className="size-4" aria-hidden /> {meta.label}
          </p>
          {editing ? (
            <Input
              aria-label="Title"
              value={title ?? r.title}
              onChange={(e) => setTitle(e.target.value)}
              className="mt-1 text-h3"
            />
          ) : (
            <h1 className="mt-1 text-h1 text-balance text-text">{r.title}</h1>
          )}
          {r.query && r.query !== r.title && <p className="mt-1 text-body text-muted">{r.query}</p>}
          <p className="mt-1.5 text-caption text-subtle">
            {r.document_ids.length ? `${r.document_ids.length} papers · ` : ''}
            {r.generation_config.llm_model ? `written by ${r.generation_config.llm_model} · ` : ''}
            {timeAgo(r.created_at)}
            {r.edited_at ? ` · edited ${timeAgo(r.edited_at)}` : ''}
          </p>
        </div>
        {r.status === 'ready' && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {editing ? (
              <>
                <Button variant="ghost" onClick={() => (setEditing(false), setDrafts({}), setTitle(null))}>
                  Cancel
                </Button>
                <Button onClick={save} loading={update.isPending}>
                  <Check className="size-4" aria-hidden /> Save
                </Button>
              </>
            ) : (
              <>
                <Button variant="secondary" onClick={() => setEditing(true)}>
                  <Pencil className="size-4" aria-hidden /> Edit
                </Button>
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger asChild>
                    <Button variant="secondary">
                      <Download className="size-4" aria-hidden /> Export <ChevronDown className="size-3.5" aria-hidden />
                    </Button>
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content align="end" sideOffset={4} className="z-50 min-w-40 rounded-md border border-border bg-surface-elevated p-1 shadow-lg">
                      {(
                        [
                          ['md', 'Markdown (.md)'],
                          ['docx', 'Word (.docx)'],
                          ['pdf', 'PDF'],
                        ] as const
                      ).map(([format, label]) => (
                        <DropdownMenu.Item
                          key={format}
                          onSelect={() => void download(format)}
                          className="cursor-pointer rounded-sm px-2 py-1.5 text-small text-text outline-none data-[highlighted]:bg-surface-muted"
                        >
                          {label}
                        </DropdownMenu.Item>
                      ))}
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </>
            )}
            <Button
              variant="ghost"
              size="icon"
              aria-label="Delete report"
              onClick={() => {
                if (window.confirm('Delete this report?')) remove.mutate(r.id, { onSuccess: () => navigate('/reviews') })
              }}
            >
              <Trash2 className="size-4" aria-hidden />
            </Button>
          </div>
        )}
      </header>

      {(r.status === 'queued' || r.status === 'running') && <Progress report={r} />}
      {r.status === 'failed' && (
        <Card className="border-error/40 bg-error-soft/40 p-5">
          <p className="flex items-center gap-2 font-medium text-error">
            <AlertTriangle className="size-4" aria-hidden /> {r.error_message ?? 'The report couldn’t be written.'}
          </p>
          {r.error_hint && <p className="mt-1 text-small text-muted">{r.error_hint}</p>}
          <Link to={`/reviews?kind=${r.kind}`} className="mt-3 inline-block text-small text-primary hover:underline">
            Start a new {meta.label.toLowerCase()}
          </Link>
        </Card>
      )}

      {r.status === 'ready' && (
        <div className="space-y-8">
          {r.support && (
            <p className="rounded-md border border-border bg-surface-muted/50 px-3 py-2 text-small text-muted">
              {r.support.explanation} Hover a status dot for details; click a number to see the passage.
              {r.trace.summaries_written?.length
                ? ` ${r.trace.summaries_written.length} paper summar${r.trace.summaries_written.length === 1 ? 'y was' : 'ies were'} written for this report.`
                : ''}
              {r.trace.skipped?.length
                ? ` Skipped ${r.trace.skipped.length}: ${[...new Set(r.trace.skipped.map((s) => SKIP_REASONS[s.reason] ?? s.reason))].join(', ')}.`
                : ''}
            </p>
          )}
          {r.kind === 'deep_research' && <ResearchTrace report={r} />}
          {r.sections.map((section) => (
            <section key={section.key} aria-labelledby={`section-${section.key}`}>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <h2 id={`section-${section.key}`} className="text-h2 text-text">
                  {section.title}
                </h2>
                <SectionStatus section={section} />
              </div>
              {section.kind === 'table' ? (
                <ComparisonTable section={section} renderCite={renderCite} />
              ) : section.kind === 'disagreements' ? (
                <Disagreements section={section} renderCite={renderCite} />
              ) : section.kind === 'gaps' ? (
                <Gaps section={section} renderCite={renderCite} />
              ) : section.kind === 'chronology' && !editing ? (
                <Chronology section={section} />
              ) : (
                <TextSection
                  section={section}
                  renderCite={renderCite}
                  editing={editing}
                  draft={drafts[section.key]}
                  onDraft={(text) => setDrafts((d) => ({ ...d, [section.key]: text }))}
                />
              )}
              {!editing && (section.removed?.length ?? 0) > 0 && (
                <details className="mt-2 text-small">
                  <summary className="cursor-pointer text-caption text-subtle">
                    {section.removed!.length} sentence{section.removed!.length === 1 ? '' : 's'} removed by the check
                  </summary>
                  <p className="mt-1 text-caption text-subtle">
                    The model wrote these, but none of the passages it was given supports them (comparisons across
                    papers often can’t be checked one passage at a time). Edit the section to add one back.
                  </p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted">
                    {section.removed!.map((r, i) => (
                      <li key={i}>
                        {r.text} <span className="text-caption text-subtle">— {r.reason}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {section.data?.papers && section.kind === 'text' && !editing && (
                <p className="mt-2 text-caption text-subtle">
                  Papers: {section.data.papers.map((p) => p.title).join('; ')}
                  {section.data.name_source === 'model' ? ' · theme named by the AI model' : ''}
                </p>
              )}
            </section>
          ))}
          {r.sources.length > 0 && (
            <details className="rounded-lg border border-border bg-surface p-4">
              <summary className="cursor-pointer text-small font-medium text-text">Sources ({r.sources.length} passages)</summary>
              <ol className="mt-3 space-y-2">
                {r.sources.map((s) => (
                  <li key={s.number} className="text-small">
                    <span className="mr-1.5 text-caption text-subtle tabular-nums">[{s.number}]</span>
                    {s.document.id ? (
                      <Link to={`/papers/${s.document.id}?tab=paper&page=${s.page_start}`} className="text-text hover:text-primary">
                        {s.document.title}
                      </Link>
                    ) : (
                      s.document.title
                    )}
                    <span className="text-caption text-subtle">
                      {' '}
                      · {s.section_title || 'Front matter'}, p. {s.page_start}
                    </span>
                    <p className="mt-0.5 line-clamp-2 text-caption text-muted">{s.quote}</p>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
    </PageContainer>
  )
}
