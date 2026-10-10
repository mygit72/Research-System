import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check, ChevronRight, Copy, Info, Layers, Loader2, RefreshCw, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { SupportBadge } from '@/components/chat/Answer'
import { Markdown } from '@/components/chat/Markdown'
import { citationRenderer } from '@/components/chat/citations'
import { SourceCard, type OpenSource } from '@/components/chat/Sources'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import { ErrorState, ProgressBar, Skeleton } from '@/components/ui/Feedback'
import { Sheet } from '@/components/ui/Sheet'
import { Tooltip } from '@/components/ui/Tooltip'
import { isWriting, useGenerateSummary, useSummary } from '@/hooks/useSummary'
import { cn } from '@/lib/cn'
import { summaryMarkdown } from '@/lib/summary'
import { systemApi } from '@/services/api'
import type { DocumentDetail, PaperSummary, SummarySection, Verification } from '@/types/api'

type RenderCite = ReturnType<typeof citationRenderer>

const STATUS_DOT: Record<SummarySection['status'], string> = {
  supported: 'bg-success',
  partial: 'bg-warning',
  unsupported: 'bg-error',
  unverified: 'bg-subtle',
  not_reported: 'bg-border-strong',
}

function SectionStatus({ section }: { section: SummarySection }) {
  // Only problems are spelled out; a well-supported section just shows its dot.
  const quiet = section.status === 'supported'
  return (
    <Tooltip content={`${section.label}. ${section.explanation}`}>
      <span className="inline-flex shrink-0 items-center gap-1.5 text-caption text-muted" tabIndex={0}>
        <span className={cn('size-2 rounded-full', STATUS_DOT[section.status])} aria-hidden />
        <span className={cn(quiet && 'sr-only')}>{section.label}</span>
      </span>
    </Tooltip>
  )
}

function SectionItem({ section, renderCite }: { section: SummarySection; renderCite: RenderCite }) {
  const [open, setOpen] = useState(true)
  const id = `summary-${section.key}`
  if (section.status === 'not_reported')
    return (
      <div className="flex items-baseline justify-between gap-3 py-3 pl-6">
        <h3 className="text-small font-semibold text-text">{section.title}</h3>
        <Tooltip content="The paper’s passages don’t cover this, so nothing was guessed.">
          <span className="text-caption text-subtle italic" tabIndex={0}>
            Not reported
          </span>
        </Tooltip>
      </div>
    )
  return (
    <div className="py-3">
      <div className="flex items-center gap-3">
        <h3 className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-controls={id}
            className="flex w-full items-center gap-2 text-left text-small font-semibold text-text hover:text-primary"
          >
            <ChevronRight className={cn('size-4 shrink-0 text-muted transition-transform', open && 'rotate-90')} aria-hidden />
            {section.title}
          </button>
        </h3>
        <SectionStatus section={section} />
      </div>
      {open && (
        <div id={id} className="mt-1.5 pl-6 text-body text-text">
          <Markdown text={section.text} renderCite={renderCite} />
        </div>
      )}
    </div>
  )
}

function asVerification(summary: PaperSummary): Verification | null {
  if (!summary.support) return null
  return {
    status: summary.support.status,
    label: summary.support.label,
    explanation:
      summary.support.explanation +
      (summary.support.not_reported.length ? ` Not reported in the paper: ${summary.support.not_reported.join(', ')}.` : ''),
    verifier: summary.support.verifier,
    claims: summary.sections.flatMap((s) => s.claims),
  }
}

function SummaryBody({
  summary,
  onOpen,
  dimmed,
}: {
  summary: PaperSummary
  onOpen?: OpenSource
  dimmed?: boolean
}) {
  const renderCite = useMemo(() => citationRenderer(summary.sources, null, onOpen), [summary.sources, onOpen])
  const takeaway = summary.sections.find((s) => s.key === 'takeaway')
  const sections = summary.sections.filter((s) => s.key !== 'takeaway')
  return (
    <div className={cn(dimmed && 'opacity-60')}>
      {takeaway && takeaway.status !== 'not_reported' && (
        <div className="mb-3 rounded-md border-l-2 border-primary bg-primary-soft/40 px-4 py-3">
          <p className="mb-1 flex items-center justify-between gap-2 text-caption font-medium tracking-wide text-primary uppercase">
            One-line takeaway
            <SectionStatus section={takeaway} />
          </p>
          <div className="text-body text-text">
            <Markdown text={takeaway.text} renderCite={renderCite} />
          </div>
        </div>
      )}
      <div className="divide-y divide-border">
        {sections.map((section) => (
          <SectionItem key={section.key} section={section} renderCite={renderCite} />
        ))}
      </div>
    </div>
  )
}

function SourcesSheet({
  summary,
  open,
  onOpenChange,
  onOpen,
}: {
  summary: PaperSummary
  open: boolean
  onOpenChange: (open: boolean) => void
  onOpen?: OpenSource
}) {
  const cited = new Set(summary.sections.flatMap((s) => s.citations))
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Summary sources" className="w-[min(32rem,calc(100vw-2rem))]">
      <p className="mb-4 text-small text-muted">
        The summary was written only from these {summary.sources.length} passages of the paper; {cited.size} are cited.
      </p>
      <ol className="space-y-4">
        {summary.sources.map((item) => (
          <li
            key={item.number}
            className={cn('rounded-lg border p-3', cited.has(item.number) ? 'border-border-strong' : 'border-border opacity-80')}
          >
            {cited.has(item.number) && (
              <Badge tone="primary" className="mb-2">
                Cited in the summary
              </Badge>
            )}
            <SourceCard
              item={item}
              reranker={null}
              onOpen={
                onOpen &&
                ((source) => {
                  onOpenChange(false)
                  onOpen(source)
                })
              }
            />
          </li>
        ))}
      </ol>
    </Sheet>
  )
}

function Meta({ summary, onSources }: { summary: PaperSummary; onSources: () => void }) {
  const model = summary.generation_config.llm_model
  const seconds = summary.latency_ms != null ? Math.round(summary.latency_ms / 1000) : null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-3 text-caption text-muted">
      <span>
        Written by {model ?? 'the language model'} from {summary.sources.length} passage
        {summary.sources.length === 1 ? '' : 's'} of this paper{seconds != null && ` in ${seconds} s`}
      </span>
      {summary.sources.length > 0 && (
        <Button variant="ghost" size="sm" className="h-7 px-2 text-caption" onClick={onSources}>
          <Layers className="size-3.5" aria-hidden /> View sources ({summary.sources.length})
        </Button>
      )}
    </div>
  )
}

function NotReadyReason({ doc }: { doc: DocumentDetail }) {
  const ai = useQuery({ queryKey: ['ai-status'], queryFn: systemApi.aiStatus, staleTime: 30_000 })
  const llm = ai.data?.llm
  let reason: { message: string; hint?: string | null } | null = null
  if (doc.index_status === 'pending') reason = { message: 'Available once the paper has been indexed for search.' }
  else if (doc.index_status === 'failed')
    reason = { message: 'This paper couldn’t be indexed, so there are no passages to summarize. Retry indexing first.' }
  else if (llm && !llm.ready) reason = { message: `The language model isn’t ready. ${llm.problem ?? ''}`, hint: llm.hint }
  if (!reason) return null
  return (
    <div className="mt-3 flex gap-2 rounded-md border border-warning/30 bg-warning-soft/50 p-3 text-small">
      <Info className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
      <div>
        <p className="text-text">{reason.message}</p>
        {reason.hint && <p className="mt-0.5 font-mono text-caption text-muted">{reason.hint}</p>}
      </div>
    </div>
  )
}

export function SummaryCard({ doc, onOpenSource }: { doc: DocumentDetail; onOpenSource?: OpenSource }) {
  const query = useSummary(doc.id)
  const generate = useGenerateSummary(doc.id)
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const summary = query.data ?? null
  const writing = isWriting(summary)
  // What to show as content: this summary when ready; otherwise what's done of it so far,
  // or the previous summary (kept until the new one is ready).
  const shown =
    summary?.status === 'ready'
      ? summary
      : summary?.sections.length
        ? summary
        : (summary?.previous ?? null)
  const verification = shown?.status === 'ready' ? asVerification(shown) : null
  const canGenerate = doc.status === 'ready' && doc.index_status === 'indexed'

  const copy = () => {
    if (!shown) return
    void navigator.clipboard?.writeText(summaryMarkdown(doc.title, shown)).then(() => {
      setCopied(true)
      toast.success('Summary copied with its sources')
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <Card id="ai-summary" className="scroll-mt-20">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden /> AI summary
          </CardTitle>
          <CardDescription>
            Written only from this paper’s passages. Click a number to see where a statement comes from.
          </CardDescription>
        </div>
        {shown?.status === 'ready' && (
          <div className="flex flex-wrap items-center gap-1">
            {verification && <SupportBadge verification={verification} />}
            <Button variant="ghost" size="sm" className="h-7 px-2 text-caption" onClick={copy} aria-label="Copy summary">
              {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />} Copy
            </Button>
            <Tooltip content="Write a new summary (the current one stays until it’s ready)">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-caption"
                onClick={() => generate.mutate(true)}
                disabled={writing || generate.isPending || !canGenerate}
              >
                <RefreshCw className="size-3.5" aria-hidden /> Regenerate
              </Button>
            </Tooltip>
          </div>
        )}
      </CardHeader>
      <CardBody>
        {query.isPending ? (
          <div className="space-y-3" aria-busy="true" aria-label="Loading summary">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        ) : query.isError ? (
          <ErrorState error={query.error} title="We couldn't load the summary" onRetry={() => query.refetch()} />
        ) : (
          <>
            {!summary && (
              <div>
                <p className="max-w-prose text-small text-muted">
                  A structured summary — problem, motivation, method, data, experiments, results, limitations,
                  future work and key contribution — where every statement cites the page it came from and is
                  checked against it. Parts the paper doesn’t cover are marked “Not reported” instead of guessed.
                </p>
                <Button
                  className="mt-4"
                  onClick={() => generate.mutate(false)}
                  loading={generate.isPending}
                  disabled={!canGenerate}
                >
                  {!generate.isPending && <Sparkles className="size-4" aria-hidden />} Generate summary
                </Button>
                <NotReadyReason doc={doc} />
              </div>
            )}

            {summary && writing && (
              <div className="mb-4 rounded-md border border-border bg-surface-muted/50 p-4" aria-live="polite">
                <p className="flex items-center gap-2 text-small font-medium text-text">
                  <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
                  {summary.status === 'queued' ? 'Waiting to start…' : `${summary.progress?.detail ?? 'Writing the summary'}…`}
                </p>
                <ProgressBar className="mt-3" value={summary.progress?.progress ?? 0} label="Summary progress" />
                <p className="mt-2 text-caption text-muted">
                  The paper is read part by part, so sections appear as they’re written. With a local model on a
                  CPU this takes a minute or two.
                  {!summary.sections.length && summary.previous && ' The previous summary is shown until then.'}
                </p>
              </div>
            )}

            {summary?.status === 'failed' && (
              <div role="alert" className="mb-4 flex gap-2.5 rounded-md border border-error/30 bg-error-soft p-3 text-small">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-error" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-text">The summary couldn’t be written. {summary.error_message}</p>
                  {summary.error_hint && <p className="mt-0.5 font-mono text-caption text-muted">{summary.error_hint}</p>}
                  {summary.previous && <p className="mt-1 text-caption text-muted">Showing the previous summary.</p>}
                </div>
                <Button variant="secondary" size="sm" onClick={() => generate.mutate(false)} loading={generate.isPending}>
                  Try again
                </Button>
              </div>
            )}

            {shown?.stale && shown.status === 'ready' && (
              <div className="mb-3 flex items-start gap-2 rounded-md border border-info/30 bg-info-soft p-3 text-small text-text">
                <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
                <p className="flex-1">{shown.stale}</p>
              </div>
            )}

            {shown && (
              <>
                <SummaryBody summary={shown} onOpen={onOpenSource} dimmed={shown !== summary && writing} />
                {shown.status === 'ready' && <Meta summary={shown} onSources={() => setSourcesOpen(true)} />}
                <SourcesSheet summary={shown} open={sourcesOpen} onOpenChange={setSourcesOpen} onOpen={onOpenSource} />
              </>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}
