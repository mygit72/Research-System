import { useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { ArrowUpRight, BookOpenText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { SaveActions } from '@/components/organization/SaveActions'
import { Tooltip } from '@/components/ui/Tooltip'
import { CLAIM_STATUS, pagesLabel, sourceLink } from '@/lib/chat'
import { cn } from '@/lib/cn'
import type { EvidenceItem } from '@/types/api'

/** Opens a source inside the page (split view: the reader next to the chat). */
export type OpenSource = (item: EvidenceItem) => void

function SourceAction({ item, onOpen }: { item: EvidenceItem; onOpen?: OpenSource }) {
  if (!item.document.id)
    return <span className="text-caption text-subtle">This paper was deleted</span>
  if (onOpen)
    return (
      <button
        type="button"
        onClick={() => onOpen(item)}
        className="inline-flex items-center gap-1 text-small font-medium text-primary hover:underline"
      >
        <BookOpenText className="size-3.5" aria-hidden /> Show in paper
      </button>
    )
  return (
    <Link
      to={sourceLink(item)}
      state={{ boxes: item.boxes }}
      className="inline-flex items-center gap-1 text-small font-medium text-primary hover:underline"
    >
      Open paper <ArrowUpRight className="size-3.5" aria-hidden />
    </Link>
  )
}

export function Relevance({ item, reranker }: { item: EvidenceItem; reranker: string | null }) {
  // Only a reranker's score is a probability with a meaning of its own; fused scores are ranks.
  if (!reranker) return null
  return (
    <Tooltip content={`How likely the reranker (${reranker.split('/').pop()}) judged this passage to answer the question`}>
      <span className="text-caption text-muted tabular-nums">Relevance {item.score.toFixed(2)}</span>
    </Tooltip>
  )
}

function Quote({ text, limit = 420 }: { text: string; limit?: number }) {
  const [full, setFull] = useState(false)
  const long = text.length > limit
  return (
    <div>
      <p className="text-small leading-relaxed whitespace-pre-line text-text">
        {full || !long ? text : `${text.slice(0, limit).trimEnd()}…`}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setFull(!full)}
          className="mt-1 text-caption text-muted hover:text-text"
          aria-expanded={full}
        >
          {full ? 'Show less' : 'Show full passage'}
        </button>
      )}
    </div>
  )
}

export function SourceCard({
  item,
  reranker,
  onOpen,
  quoteLimit,
}: {
  item: EvidenceItem
  reranker: string | null
  onOpen?: OpenSource
  quoteLimit?: number
}) {
  const status = item.support_status ? CLAIM_STATUS[item.support_status] : null
  return (
    <div className="space-y-2">
      <div>
        <p className="text-small font-semibold text-text">
          <span className="mr-1.5 text-muted tabular-nums">[{item.number}]</span>
          {item.document.title}
          {item.document.year && <span className="font-normal text-muted"> ({item.document.year})</span>}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-caption text-muted">
          <span>{pagesLabel(item)}</span>
          {item.section_title && (
            <>
              <span aria-hidden>·</span>
              <span>Section: {item.section_title}</span>
            </>
          )}
        </p>
      </div>
      <Quote text={item.quote} limit={quoteLimit} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {status && (
          <span className="inline-flex items-center gap-1.5 text-caption text-muted">
            <span className={cn('size-2 rounded-full', status.dot)} aria-hidden />
            {status.label}
          </span>
        )}
        <Relevance item={item} reranker={reranker} />
        <span className="ml-auto inline-flex items-center gap-2">
          {item.document.id && (
            <SaveActions
              compact
              documentId={item.document.id}
              kind="citation"
              target={{
                page: item.page_start,
                char_start: item.char_start,
                quote: item.quote.slice(0, 1200),
                boxes: item.boxes,
                section_title: item.section_title || undefined,
                chunk_id: item.chunk_id ?? undefined,
              }}
            />
          )}
          <SourceAction item={item} onOpen={onOpen} />
        </span>
      </div>
    </div>
  )
}

/** An inline [n] marker. Click shows the source (or, in split view, jumps the reader to it). */
export function CitationChip({
  item,
  reranker,
  onOpen,
}: {
  item: EvidenceItem
  reranker: string | null
  onOpen?: OpenSource
}) {
  const chip = (props: Record<string, unknown> = {}) => (
    <button
      type="button"
      aria-label={`Source ${item.number}: ${item.document.title}, ${pagesLabel(item)}`}
      className="mx-0.5 inline-flex h-[1.15rem] min-w-[1.15rem] -translate-y-px items-center justify-center rounded-sm bg-primary-soft px-1 align-baseline text-[0.7rem] font-semibold text-primary tabular-nums transition-colors hover:bg-primary hover:text-primary-fg"
      {...props}
    >
      {item.number}
    </button>
  )
  if (onOpen && item.document.id)
    return (
      <Tooltip content={`${item.document.title} · ${pagesLabel(item)}`}>
        {chip({ onClick: () => onOpen(item) })}
      </Tooltip>
    )
  return (
    <Popover.Root>
      <Popover.Trigger asChild>{chip()}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          collisionPadding={12}
          className="z-50 w-[min(26rem,calc(100vw-2rem))] rounded-lg border border-border bg-surface-elevated p-4 shadow-lg animate-fade-in"
        >
          <p className="mb-2 text-caption font-medium tracking-wide text-subtle uppercase">Source</p>
          <SourceCard item={item} reranker={reranker} onOpen={onOpen} quoteLimit={360} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
