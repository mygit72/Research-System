import { useMemo, useState } from 'react'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, Download, Info, Layers, Loader2, Pin, PinOff, RefreshCw, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { SupportBadge } from '@/components/chat/Answer'
import { Markdown } from '@/components/chat/Markdown'
import { citationRenderer } from '@/components/chat/citations'
import { SourceCard } from '@/components/chat/Sources'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/Card'
import { ErrorState, ProgressBar, Skeleton } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'
import { Sheet } from '@/components/ui/Sheet'
import { Tooltip } from '@/components/ui/Tooltip'
import {
  AGREEMENT,
  KIND_LABELS,
  STATUS_LABEL,
  comparisonCsv,
  comparisonMarkdown,
  download,
  fileName,
} from '@/lib/compare'
import { cn } from '@/lib/cn'
import { queryClient } from '@/lib/queryClient'
import { comparisonsApi } from '@/services/api'
import type { Comparison, ComparisonCell, ComparisonColumn, Verification } from '@/types/api'

type RenderCite = ReturnType<typeof citationRenderer>

const DOT: Record<ComparisonCell['status'], string> = {
  supported: 'bg-success',
  partial: 'bg-warning',
  unsupported: 'bg-error',
  unverified: 'bg-subtle',
  not_reported: 'bg-border-strong',
}

const itemClass =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

function asVerification(comparison: Comparison): Verification | null {
  const support = comparison.support
  if (!support) return null
  return {
    status: support.status,
    label: support.label,
    explanation: support.explanation,
    verifier: support.verifier,
    claims: [...comparison.rows.flatMap((r) => r.cells.flatMap((c) => c.claims)), ...(comparison.overview?.claims ?? [])],
  }
}

function Cell({ cell, renderCite }: { cell: ComparisonCell; renderCite: RenderCite }) {
  if (cell.status === 'not_reported')
    return (
      <Tooltip content="The paper’s passages don’t say, so nothing was guessed.">
        <span className="text-small text-subtle italic" tabIndex={0}>
          Not reported
        </span>
      </Tooltip>
    )
  const quiet = cell.status === 'supported'
  return (
    <div className="space-y-1.5">
      <div className="text-small leading-relaxed text-text">
        <Markdown text={cell.text} renderCite={renderCite} />
      </div>
      <Tooltip content={`${cell.label}. ${cell.explanation}`}>
        <span className="inline-flex items-center gap-1.5 text-caption text-muted" tabIndex={0}>
          <span className={cn('size-2 rounded-full', DOT[cell.status])} aria-hidden />
          <span className={cn(quiet && 'sr-only')}>{cell.label}</span>
        </span>
      </Tooltip>
    </div>
  )
}

function ColumnHeader({
  column,
  pinned,
  onPin,
}: {
  column: ComparisonColumn
  pinned: boolean
  onPin: () => void
}) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary-soft text-caption font-semibold text-primary">
        {column.letter}
      </span>
      <div className="min-w-0 flex-1">
        {column.deleted ? (
          <span className="line-clamp-2 text-small font-semibold text-muted line-through">{column.title}</span>
        ) : (
          <Link to={`/papers/${column.document_id}`} className="line-clamp-2 text-small font-semibold text-text hover:text-primary">
            {column.title}
          </Link>
        )}
        <span className="text-caption font-normal text-muted">
          {column.deleted ? 'Deleted' : [column.year, column.authors_display].filter(Boolean).join(' · ')}
        </span>
      </div>
      <Tooltip content={pinned ? 'Unpin column' : 'Pin column (keeps it in view while scrolling)'}>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-pressed={pinned}
          aria-label={`${pinned ? 'Unpin' : 'Pin'} ${column.title}`}
          onClick={onPin}
        >
          {pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}
        </Button>
      </Tooltip>
    </div>
  )
}

export function ComparisonTable({
  comparison,
  highlight,
  renderCite,
}: {
  comparison: Comparison
  highlight: boolean
  renderCite: RenderCite
}) {
  const [pinned, setPinned] = useState<string | null>(null)
  // A pinned paper moves next to the category column and stays there while scrolling.
  const order = useMemo(() => {
    const indexes = comparison.columns.map((_, i) => i)
    const at = comparison.columns.findIndex((c) => c.document_id === pinned)
    return at < 0 ? indexes : [at, ...indexes.filter((i) => i !== at)]
  }, [comparison.columns, pinned])
  const stickyPinned = (i: number) =>
    comparison.columns[i].document_id === pinned && 'sticky left-36 z-10 shadow-[1px_0_0_var(--border)] sm:left-44'

  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-surface" role="region" aria-label="Comparison table" tabIndex={0}>
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="sticky left-0 z-20 w-36 min-w-36 bg-surface-muted px-3 py-3 text-caption font-medium text-muted sm:w-44 sm:min-w-44">
              Category
            </th>
            {order.map((i) => {
              const column = comparison.columns[i]
              return (
                <th
                  key={column.document_id}
                  scope="col"
                  className={cn('min-w-[16rem] bg-surface-muted px-3 py-3 align-top font-normal', stickyPinned(i))}
                >
                  <ColumnHeader
                    column={column}
                    pinned={column.document_id === pinned}
                    onPin={() => setPinned(column.document_id === pinned ? null : column.document_id)}
                  />
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {comparison.rows.map((row) => {
            const meta = AGREEMENT[row.agreement]
            const marked = highlight && (row.agreement === 'different' || row.agreement === 'partial')
            const background = marked ? 'bg-warning-soft' : 'bg-surface'
            return (
              <tr key={row.key} className={cn(marked && 'bg-warning-soft/60')} data-agreement={row.agreement}>
                <th scope="row" className={cn('sticky left-0 z-10 px-3 py-3 align-top', background)}>
                  <span className="block text-small font-semibold text-text">{row.title}</span>
                  {highlight && (
                    <Tooltip content={meta.hint}>
                      <span className="mt-1 inline-flex items-center gap-1 text-caption font-normal text-muted" tabIndex={0}>
                        <span className={cn('size-1.5 rounded-full', meta.dot)} aria-hidden /> {meta.label}
                      </span>
                    </Tooltip>
                  )}
                </th>
                {order.map((i) => (
                  <td key={comparison.columns[i].document_id} className={cn('px-3 py-3 align-top', stickyPinned(i) && cn(stickyPinned(i), background))}>
                    <Cell cell={row.cells[i]} renderCite={renderCite} />
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function AgreementCount({ comparison }: { comparison: Comparison }) {
  const count = (agreement: string) => comparison.rows.filter((r) => r.agreement === agreement).length
  const parts = [
    `${count('different')} of ${comparison.rows.length} rows differ`,
    count('partial') && `${count('partial')} not reported by every paper`,
    count('similar') && `${count('similar')} similar`,
    count('none') && `${count('none')} reported by none`,
  ].filter(Boolean)
  return (
    <p className="mb-2 text-small text-muted" role="status">
      {parts.join(' · ')}. Compared by the words each paper uses, so related ideas in different words count as
      different.
    </p>
  )
}

function SourcesSheet({ comparison, open, onOpenChange }: { comparison: Comparison; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Comparison sources" className="w-[min(32rem,calc(100vw-2rem))]">
      <p className="mb-4 text-small text-muted">
        Every cell was written only from these {comparison.sources.length} passages of the compared papers.
      </p>
      {comparison.columns.map((column) => {
        const items = comparison.sources.filter((s) => s.letter === column.letter)
        if (!items.length) return null
        return (
          <section key={column.document_id} className="mb-6">
            <h3 className="mb-2 text-small font-semibold text-text">
              {column.letter}. {column.title}
            </h3>
            <ol className="space-y-3">
              {items.map((item) => (
                <li key={item.number} className="rounded-lg border border-border p-3">
                  <SourceCard item={item} reranker={null} />
                </li>
              ))}
            </ol>
          </section>
        )
      })}
    </Sheet>
  )
}

export function ComparisonPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [highlight, setHighlight] = useState(false)
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const query = useQuery({
    queryKey: ['comparisons', id],
    queryFn: () => comparisonsApi.get(id),
    refetchInterval: (q) => (q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 1500 : false),
  })
  const comparison = query.data
  const renderCite = useMemo(() => citationRenderer(comparison?.sources ?? [], null), [comparison?.sources])
  const again = useMutation({
    mutationFn: (force: boolean) =>
      comparisonsApi.create({ document_ids: comparison!.columns.map((c) => c.document_id), kind: comparison!.kind, force }),
    onSuccess: (next) => {
      void queryClient.invalidateQueries({ queryKey: ['comparisons'] })
      queryClient.setQueryData(['comparisons', next.id], next)
      if (next.id !== id) navigate(`/compare/${next.id}`, { replace: true })
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => comparisonsApi.remove(id),
    onSuccess: () => {
      toast.success('Comparison deleted')
      void queryClient.invalidateQueries({ queryKey: ['comparisons'] })
      navigate('/compare', { replace: true })
    },
    onError: (e) => toast.error(e.message),
  })

  if (query.isPending)
    return (
      <PageContainer width="wide">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="mt-6 h-40 w-full" />
        <Skeleton className="mt-6 h-96 w-full" />
      </PageContainer>
    )
  if (query.isError || !comparison)
    return (
      <PageContainer>
        <ErrorState error={query.error} title="We couldn't open this comparison" onRetry={() => query.refetch()} />
      </PageContainer>
    )

  const writing = comparison.status === 'queued' || comparison.status === 'running'
  const ready = comparison.status === 'ready'
  const verification = ready ? asVerification(comparison) : null
  const anyDeleted = comparison.columns.some((c) => c.deleted)
  const status = STATUS_LABEL[comparison.status]

  return (
    <PageContainer width="wide">
      <Link to="/compare" className="inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-3.5" /> Compare
      </Link>
      <header className="mt-3 mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-h1 text-balance text-text">{comparison.title}</h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-small text-muted">
            <Badge>{KIND_LABELS[comparison.kind]}</Badge>
            <span>{comparison.columns.length} papers</span>
            {!ready && <Badge tone={status.tone}>{status.label}</Badge>}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {ready && (
            <>
              <Button
                variant={highlight ? 'primary' : 'secondary'}
                size="sm"
                aria-pressed={highlight}
                onClick={() => setHighlight(!highlight)}
              >
                Highlight differences
              </Button>
              <Dropdown.Root>
                <Dropdown.Trigger asChild>
                  <Button variant="secondary" size="sm">
                    <Download className="size-4" aria-hidden /> Export
                  </Button>
                </Dropdown.Trigger>
                <Dropdown.Portal>
                  <Dropdown.Content align="end" sideOffset={6} className="z-50 w-52 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in">
                    <Dropdown.Item
                      className={itemClass}
                      onSelect={() => download(fileName(comparison.title, 'md'), comparisonMarkdown(comparison), 'text/markdown')}
                    >
                      Markdown (.md)
                    </Dropdown.Item>
                    <Dropdown.Item
                      className={itemClass}
                      onSelect={() => download(fileName(comparison.title, 'csv'), comparisonCsv(comparison), 'text/csv')}
                    >
                      Spreadsheet (.csv)
                    </Dropdown.Item>
                    <Dropdown.Item
                      className={itemClass}
                      onSelect={() =>
                        void navigator.clipboard?.writeText(comparisonMarkdown(comparison)).then(() => toast.success('Copied as Markdown'))
                      }
                    >
                      Copy as Markdown
                    </Dropdown.Item>
                  </Dropdown.Content>
                </Dropdown.Portal>
              </Dropdown.Root>
              <Tooltip content={anyDeleted ? 'A paper was deleted; start a new comparison' : 'Write the comparison again'}>
                <span>
                  <Button variant="secondary" size="sm" onClick={() => again.mutate(true)} loading={again.isPending} disabled={anyDeleted}>
                    {!again.isPending && <RefreshCw className="size-4" aria-hidden />} Regenerate
                  </Button>
                </span>
              </Tooltip>
            </>
          )}
          <Button variant="ghost" size="icon-sm" aria-label="Delete comparison" onClick={() => remove.mutate()}>
            <Trash2 className="size-4" />
          </Button>
        </div>
      </header>

      {writing && (
        <div className="mb-6 rounded-lg border border-border bg-surface p-4" aria-live="polite">
          <p className="flex items-center gap-2 text-small font-medium text-text">
            <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
            {comparison.status === 'queued' ? 'Waiting to start…' : `${comparison.progress?.detail ?? 'Comparing'}…`}
          </p>
          <ProgressBar className="mt-3" value={comparison.progress?.progress ?? 0} label="Comparison progress" />
          <p className="mt-2 text-caption text-muted">
            Each paper is read part by part and its column fills in when it’s done. Papers compared before are reused. With a
            local model on a CPU this takes about a minute per new paper.
          </p>
        </div>
      )}

      {comparison.status === 'failed' && (
        <div role="alert" className="mb-6 flex gap-2.5 rounded-md border border-error/30 bg-error-soft p-3 text-small">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-error" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-text">The comparison couldn’t be written. {comparison.error_message}</p>
            {comparison.error_hint && <p className="mt-0.5 font-mono text-caption text-muted">{comparison.error_hint}</p>}
          </div>
          {!anyDeleted && (
            <Button variant="secondary" size="sm" onClick={() => again.mutate(false)} loading={again.isPending}>
              Try again
            </Button>
          )}
        </div>
      )}

      {comparison.stale && (
        <div className="mb-6 flex items-start gap-2 rounded-md border border-info/30 bg-info-soft p-3 text-small text-text">
          <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
          <p>{comparison.stale}</p>
        </div>
      )}

      {ready && comparison.overview && comparison.overview.status !== 'not_reported' && (
        <Card className="mb-6">
          <CardHeader className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Overview</CardTitle>
            {verification && <SupportBadge verification={verification} />}
          </CardHeader>
          <CardBody>
            <div className="max-w-prose text-body leading-7 text-text">
              <Markdown text={comparison.overview.text} renderCite={renderCite} />
            </div>
          </CardBody>
        </Card>
      )}

      {comparison.rows.length > 0 && (
        <>
          {highlight && <AgreementCount comparison={comparison} />}
          <ComparisonTable comparison={comparison} highlight={highlight} renderCite={renderCite} />
          {ready && (
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-muted">
              <span>
                Written by {comparison.generation_config.llm_model ?? 'the language model'}
                {comparison.latency_ms != null && ` in ${Math.round(comparison.latency_ms / 1000)} s`}
                {(comparison.trace.papers ?? []).some((p) => p.cached) &&
                  ` · ${(comparison.trace.papers ?? []).filter((p) => p.cached).length} paper(s) reused from earlier comparisons`}
              </span>
              <Button variant="ghost" size="sm" className="h-7 px-2 text-caption" onClick={() => setSourcesOpen(true)}>
                <Layers className="size-3.5" aria-hidden /> View sources ({comparison.sources.length})
              </Button>
            </div>
          )}
          <SourcesSheet comparison={comparison} open={sourcesOpen} onOpenChange={setSourcesOpen} />
        </>
      )}
    </PageContainer>
  )
}
