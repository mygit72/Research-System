import { useState } from 'react'
import { ArrowUpRight, ChevronDown } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/cn'
import {
  DOC_TYPE_LABELS,
  RETRIEVER_LABELS,
  SECTION_LABELS,
  describeMatch,
  highlightSegments,
  paperLink,
  type PaperGroup,
} from '@/lib/search'
import type { SearchHit } from '@/types/api'

export function HighlightedText({
  text,
  highlights,
  range,
}: {
  text: string
  highlights: [number, number][]
  range?: [number, number]
}) {
  return (
    <>
      {highlightSegments(text, highlights, range).map((segment, i) =>
        segment.mark ? (
          <mark key={i} className="rounded-sm bg-warning-soft px-0.5 font-medium text-text">
            {segment.text}
          </mark>
        ) : (
          <span key={i}>{segment.text}</span>
        ),
      )}
    </>
  )
}

/** Relevance relative to the best match in this search: honest, unlike a fake "93% confident". */
function RelevanceMeter({ score, maxScore }: { score: number; maxScore: number }) {
  const ratio = maxScore > 0 ? Math.max(0.04, Math.min(1, score / maxScore)) : 0
  const percent = Math.round(ratio * 100)
  return (
    <Tooltip content="Relevance compared with the best match in this search">
      <span
        role="meter"
        aria-label="Relevance compared with the best match"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="inline-flex h-1.5 w-14 overflow-hidden rounded-full bg-surface-muted"
      >
        <span className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
      </span>
    </Tooltip>
  )
}

function MatchBadge({ hit }: { hit: SearchHit }) {
  const detail = [
    ...Object.entries(hit.retriever_ranks).map(
      ([retriever, rank]) => `${RETRIEVER_LABELS[retriever] ?? retriever} search: #${rank}`,
    ),
    ...(hit.score_kind === 'rerank' ? [`Before reranking: #${hit.fused_rank}`] : []),
  ].join(' · ')
  const both = hit.matched_by.length > 1
  return (
    <Tooltip content={detail}>
      <span>
        <Badge tone={both ? 'primary' : 'neutral'}>{describeMatch(hit.matched_by)}</Badge>
      </span>
    </Tooltip>
  )
}

function Passage({ hit, maxScore }: { hit: SearchHit; maxScore: number }) {
  const [full, setFull] = useState(false)
  const truncated = hit.snippet[0] > 0 || hit.snippet[1] < hit.text.length
  const pages = hit.page_end > hit.page_start ? `pp. ${hit.page_start}–${hit.page_end}` : `p. ${hit.page_start}`
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted">
        <span className="font-medium text-text">
          {hit.section_title || SECTION_LABELS[hit.section_kind] || 'Passage'}
        </span>
        <span aria-hidden>·</span>
        <span>{pages}</span>
        {hit.kind !== 'text' && <Badge tone="info">{hit.kind}</Badge>}
        <span className="ml-auto">
          <RelevanceMeter score={hit.score} maxScore={maxScore} />
        </span>
      </div>
      <p className="text-small leading-relaxed whitespace-pre-line text-text">
        <HighlightedText
          text={hit.text}
          highlights={hit.highlights}
          range={full ? undefined : hit.snippet}
        />
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <MatchBadge hit={hit} />
        {truncated && (
          <button
            onClick={() => setFull(!full)}
            className="text-caption text-muted hover:text-text"
            aria-expanded={full}
          >
            {full ? 'Show less' : 'Show full passage'}
          </button>
        )}
        <Link
          to={paperLink(hit)}
          state={{ boxes: hit.boxes }}
          className="ml-auto inline-flex items-center gap-1 text-small font-medium text-primary hover:underline"
        >
          Open in paper <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      </div>
    </div>
  )
}

export function PaperResult({ group, maxScore }: { group: PaperGroup; maxScore: number }) {
  const [expanded, setExpanded] = useState(false)
  const [best, ...more] = group.hits
  const { document } = group
  return (
    <Card className="p-4 sm:p-5">
      <article aria-labelledby={`result-${best.chunk_id}`}>
        <header className="mb-3">
          <h2 id={`result-${best.chunk_id}`} className="text-body font-semibold text-text">
            <Link to={`/papers/${document.id}`} className="hover:text-primary">
              {document.title}
            </Link>
          </h2>
          <p className="mt-0.5 text-small text-muted">
            {[
              document.authors_display,
              document.year,
              document.venue,
              DOC_TYPE_LABELS[document.doc_type] ?? document.doc_type,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </header>
        <Passage hit={best} maxScore={maxScore} />
        {more.length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <button
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
              className="inline-flex items-center gap-1 text-small text-muted hover:text-text"
            >
              <ChevronDown
                className={cn('size-4 transition-transform', expanded && 'rotate-180')}
                aria-hidden
              />
              {expanded
                ? 'Hide other passages'
                : `${more.length} more matching passage${more.length === 1 ? '' : 's'} in this paper`}
            </button>
            {expanded && (
              <ol className="mt-3 space-y-5">
                {more.map((hit) => (
                  <li key={hit.chunk_id} className="border-l-2 border-border pl-4">
                    <Passage hit={hit} maxScore={maxScore} />
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </article>
    </Card>
  )
}
