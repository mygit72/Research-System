import { useMemo, useState, type ReactNode } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { AlertTriangle, Check, ChevronDown, Copy, History, Layers, Loader2, RotateCcw, Square } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Sheet } from '@/components/ui/Sheet'
import { CLAIM_STATUS, INTENT_LABELS, STAGES, SUPPORT, pagesLabel, type AnswerView } from '@/lib/chat'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { citedNumbers } from '@/lib/markdown'
import { usePreferences } from '@/stores/preferences'
import type { Verification } from '@/types/api'
import { Markdown } from './Markdown'
import { citationRenderer } from './citations'
import { SourceCard, type OpenSource } from './Sources'

export function StageIndicator({ view }: { view: AnswerView }) {
  const index = STAGES.findIndex((s) => s.stage === view.stage)
  if (index < 0) return null
  return (
    <p className="flex items-center gap-2 text-small text-muted" role="status" aria-live="polite">
      <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
      {STAGES[index].label}…
      <span className="text-caption text-subtle tabular-nums">
        {index + 1}/{STAGES.length}
      </span>
    </p>
  )
}

function verifierLabel(verifier: string) {
  if (verifier.startsWith('lexical')) return 'word overlap between each statement and its source'
  if (verifier === 'none') return 'no statements to check'
  return `an entailment model (${verifier.split('/').pop()}) that checks whether each source implies the statement`
}

export function SupportBadge({ verification }: { verification: Verification }) {
  const meta = SUPPORT[verification.status] ?? SUPPORT.unverified
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-sm px-1 py-0.5 text-caption font-medium text-muted hover:bg-surface-muted hover:text-text"
        >
          <span className={cn('size-2 rounded-full', meta.dot)} aria-hidden />
          {verification.label}
          <ChevronDown className="size-3" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          align="start"
          collisionPadding={12}
          className="z-50 max-h-[min(28rem,70vh)] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-lg border border-border bg-surface-elevated p-4 shadow-lg animate-fade-in"
        >
          <p className="text-small font-semibold text-text">{verification.label}</p>
          <p className="mt-1 text-small text-muted">{verification.explanation}</p>
          {verification.claims.length > 0 && (
            <ul className="mt-3 space-y-2 border-t border-border pt-3">
              {verification.claims.map((claim, i) => {
                const status =
                  claim.found_in != null
                    ? {
                        label: claim.citations.length
                          ? `Supported by [${claim.found_in}], not by the passage it cites`
                          : `Supported by [${claim.found_in}], but not cited`,
                        dot: 'bg-success',
                      }
                    : (CLAIM_STATUS[claim.status] ?? CLAIM_STATUS.uncited)
                return (
                  <li key={i} className="flex gap-2 text-caption">
                    <span className={cn('mt-1 size-2 shrink-0 rounded-full', status.dot)} aria-hidden />
                    <span>
                      <span className="text-text">{claim.text}</span>{' '}
                      <span className="text-muted">
                        — {status.label}
                        {claim.citations.length > 0 && ` (${claim.citations.map((n) => `[${n}]`).join('')})`}
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
          <p className="mt-3 text-caption text-subtle">Checked with {verifierLabel(verification.verifier)}.</p>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 py-1 text-caption">
      <dt className="text-muted">{label}</dt>
      <dd className="text-text">{children}</dd>
    </div>
  )
}

function RetrievalDetails({ view }: { view: AnswerView }) {
  const { analysis, trace } = view
  const dropped = trace?.context?.decisions.filter((d) => d.outcome === 'dropped') ?? []
  const years =
    analysis && (analysis.year_from || analysis.year_to)
      ? [analysis.year_from ?? '…', analysis.year_to ?? '…'].join('–')
      : null
  return (
    <dl className="divide-y divide-border">
      {analysis && (
        <>
          <Detail label="Question type">{INTENT_LABELS[analysis.intent] ?? analysis.intent}</Detail>
          <Detail label="Searched for">“{analysis.retrieval_query}”</Detail>
          {years && <Detail label="Publication years">{years}</Detail>}
          {analysis.notes.map((note) => (
            <Detail key={note} label="Note">
              {note}
            </Detail>
          ))}
        </>
      )}
      {trace?.search && (
        <>
          <Detail label="Retrieval">
            {trace.search.retrievers.join(' + ') || '—'} across {trace.search.searched_papers} paper
            {trace.search.searched_papers === 1 ? '' : 's'}
          </Detail>
          <Detail label="Reranker">{trace.search.reranker ?? 'off'}</Detail>
        </>
      )}
      {trace?.context && (
        <Detail label="Context">
          {trace.context.tokens} tokens from {view.evidence.length} passage{view.evidence.length === 1 ? '' : 's'}
        </Detail>
      )}
      {view.model && <Detail label="Model">{view.model}</Detail>}
      {view.latencyMs != null && <Detail label="Time">{(view.latencyMs / 1000).toFixed(1)} s</Detail>}
      {view.tokens && (
        <Detail label="Tokens">
          {view.tokens.input} in · {view.tokens.output} out
        </Detail>
      )}
      {dropped.length > 0 && (
        <Detail label="Not used">
          <ul className="space-y-1">
            {dropped.map((d) => (
              <li key={d.chunk_id}>
                {d.document_title}, p. {d.page} <span className="text-muted">— {d.reason}</span>
              </li>
            ))}
          </ul>
        </Detail>
      )}
    </dl>
  )
}

export function EvidencePanel({
  view,
  open,
  onOpenChange,
  onOpen,
}: {
  view: AnswerView
  open: boolean
  onOpenChange: (open: boolean) => void
  onOpen?: OpenSource
}) {
  const cited = useMemo(() => new Set(citedNumbers(view.text)), [view.text])
  const showAdvanced = usePreferences((s) => s.showAdvanced)
  const [details, setDetails] = useState(showAdvanced)
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Sources" className="w-[min(32rem,calc(100vw-2rem))]">
      <p className="mb-4 text-small text-muted">
        The answer was written only from these {view.evidence.length} passage{view.evidence.length === 1 ? '' : 's'}
        {cited.size > 0 && `; ${cited.size} ${cited.size === 1 ? 'is' : 'are'} cited`}.
      </p>
      <ol className="space-y-4">
        {view.evidence.map((item) => (
          <li
            key={item.number}
            className={cn('rounded-lg border p-3', cited.has(item.number) ? 'border-border-strong' : 'border-border opacity-80')}
          >
            {cited.has(item.number) && (
              <Badge tone="primary" className="mb-2">
                Cited in the answer
              </Badge>
            )}
            <SourceCard
              item={item}
              reranker={view.reranker}
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
      {(view.analysis || view.trace) && (
        <div className="mt-6 border-t border-border pt-4">
          <button
            type="button"
            onClick={() => setDetails(!details)}
            aria-expanded={details}
            className="flex w-full items-center justify-between text-small font-medium text-text"
          >
            How this answer was found
            <ChevronDown className={cn('size-4 text-muted transition-transform', details && 'rotate-180')} />
          </button>
          {details && (
            <div className="mt-2">
              <RetrievalDetails view={view} />
            </div>
          )}
        </div>
      )}
    </Sheet>
  )
}

function copyText(view: AnswerView) {
  const cited = new Set(citedNumbers(view.text))
  const sources = view.evidence
    .filter((e) => cited.has(e.number))
    .map((e) => `[${e.number}] ${e.document.title}${e.document.year ? ` (${e.document.year})` : ''}, ${pagesLabel(e)}`)
  return sources.length ? `${view.text}\n\nSources:\n${sources.join('\n')}` : view.text
}

/** Shown on an earlier answer reused for a near-identical question (the answer cache). */
function ReusedNotice({ view, onAnswerAgain }: { view: AnswerView; onAnswerAgain?: () => void }) {
  const reused = view.reused!
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-border bg-surface-muted px-3 py-2 text-caption text-muted">
      <History className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">
        Reused your answer to “{reused.question}” ({timeAgo(reused.asked_at)}): the same passages were found, so
        it wasn’t written again.
      </span>
      {onAnswerAgain && (
        <Button variant="ghost" size="sm" className="h-7 px-2 text-caption" onClick={onAnswerAgain}>
          <RotateCcw className="size-3.5" aria-hidden /> Answer again
        </Button>
      )}
    </div>
  )
}

export function AssistantAnswer({
  view,
  onOpen,
  onAnswerAgain,
}: {
  view: AnswerView
  onOpen?: OpenSource
  /** Ask the same question again without reusing an earlier answer. */
  onAnswerAgain?: () => void
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const streaming = view.state === 'streaming'
  const renderCite = useMemo(() => citationRenderer(view.evidence, view.reranker, onOpen), [view.evidence, view.reranker, onOpen])

  return (
    <div className="min-w-0 space-y-3">
      {streaming && (!view.text || view.stage === 'verifying') && <StageIndicator view={view} />}
      {view.text && (
        <div className={cn(streaming && view.stage === 'writing' && 'streaming-caret')}>
          <Markdown text={view.text} renderCite={renderCite} />
        </div>
      )}
      {view.reused && !streaming && <ReusedNotice view={view} onAnswerAgain={onAnswerAgain} />}
      {view.state === 'stopped' && (
        <p className="flex items-center gap-1.5 text-caption text-muted">
          <Square className="size-3" aria-hidden /> Stopped{view.text ? ' — the answer above is incomplete.' : '.'}
        </p>
      )}
      {view.error && (
        <div role="alert" className="flex gap-2.5 rounded-md border border-error/30 bg-error-soft p-3 text-small">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-error" aria-hidden />
          <div>
            <p className="font-medium text-text">{view.error.message}</p>
            {view.error.hint && <p className="mt-0.5 font-mono text-caption text-muted">{view.error.hint}</p>}
          </div>
        </div>
      )}
      {!streaming && (view.verification || view.evidence.length > 0 || view.text) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {view.verification && <SupportBadge verification={view.verification} />}
          {view.evidence.length > 0 && (
            <Button variant="ghost" size="sm" className="h-7 px-2 text-caption" onClick={() => setSourcesOpen(true)}>
              <Layers className="size-3.5" aria-hidden /> View sources ({view.evidence.length})
            </Button>
          )}
          {view.text && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-caption"
              aria-label="Copy answer"
              onClick={() => {
                void navigator.clipboard?.writeText(copyText(view)).then(() => {
                  setCopied(true)
                  toast.success('Answer copied with its sources')
                  window.setTimeout(() => setCopied(false), 1500)
                })
              }}
            >
              {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
              Copy
            </Button>
          )}
        </div>
      )}
      {view.evidence.length > 0 && (
        <EvidencePanel view={view} open={sourcesOpen} onOpenChange={setSourcesOpen} onOpen={onOpen} />
      )}
    </div>
  )
}
