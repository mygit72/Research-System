import { Link } from 'react-router-dom'
import { Quote } from 'lucide-react'
import { cn } from '@/lib/cn'
import { NODE_META, SECTION_LABELS, entityLink, evidenceLink } from '@/lib/knowledge'
import type { EntityBrief, EntityEvidence, NodeType, PaperBrief } from '@/types/api'

export function TypeDot({ type, className }: { type: NodeType; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('inline-block size-2 shrink-0 rounded-full', className)}
      style={{ background: NODE_META[type].color }}
    />
  )
}

/** A link to an entity page, coloured by type. */
export function EntityChip({
  entity,
  count,
  emphasis,
  className,
}: {
  entity: EntityBrief
  count?: number
  emphasis?: boolean
  className?: string
}) {
  return (
    <Link
      to={entityLink(entity.id)}
      title={`${NODE_META[entity.type].label}: ${entity.name}`}
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-caption font-medium transition-colors',
        emphasis
          ? 'border-transparent bg-primary-soft text-primary hover:bg-primary hover:text-primary-fg'
          : 'border-border bg-surface text-text hover:border-border-strong hover:bg-surface-muted',
        className,
      )}
    >
      <TypeDot type={entity.type} />
      <span className="truncate">{entity.name}</span>
      {count !== undefined && <span className="text-subtle tabular-nums">{count}</span>}
    </Link>
  )
}

/** Evidence sentences, each linking to its page in the reader. */
export function EvidenceList({ documentId, evidence }: { documentId: string; evidence: EntityEvidence[] }) {
  if (!evidence.length) return null
  return (
    <ul className="space-y-1.5">
      {evidence.map((e, i) => (
        <li key={`${e.page}-${i}`} className="flex gap-2 text-small">
          <Quote className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />
          <div className="min-w-0">
            <p className="text-muted">{e.quote}</p>
            <Link to={evidenceLink(documentId, e.page)} className="text-caption text-primary hover:underline">
              {SECTION_LABELS[e.section_kind] ?? 'Body'} · page {e.page}
            </Link>
          </div>
        </li>
      ))}
    </ul>
  )
}

export function PaperLine({ paper, children }: { paper: PaperBrief; children?: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <Link to={`/papers/${paper.id}`} className="font-medium text-text hover:text-primary">
        {paper.title}
      </Link>
      <p className="mt-0.5 text-small text-muted">
        {[paper.authors, paper.venue, paper.year].filter(Boolean).join(' · ') || 'No metadata'}
      </p>
      {children}
    </div>
  )
}
