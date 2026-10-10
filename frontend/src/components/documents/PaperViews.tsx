import { Bookmark as BookmarkIcon, FileCode2, FileText, FileType, Globe, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Feedback'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { READING_STATUS } from '@/lib/organization'
import type { DocumentSummary } from '@/types/api'
import { DuplicateBadge, StatusBadge } from './StatusBadge'

const TYPE_ICONS: Record<DocumentSummary['doc_type'], LucideIcon> = {
  pdf: FileText,
  docx: FileType,
  html: Globe,
  markdown: FileCode2,
  text: FileText,
}
const TYPE_LABELS: Record<DocumentSummary['doc_type'], string> = {
  pdf: 'PDF',
  docx: 'Word',
  html: 'HTML',
  markdown: 'Markdown',
  text: 'Text',
}

/** Bookmark, reading status and the first tags of a paper (nothing when it has none). */
function OrganizationLine({ doc }: { doc: DocumentSummary }) {
  const tags = doc.tags ?? []
  if (!doc.bookmarked && !doc.reading_status && !tags.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1">
      {doc.bookmarked && (
        <BookmarkIcon className="size-3.5 fill-primary text-primary" aria-label="Bookmarked" role="img" />
      )}
      {doc.reading_status && <Badge>{READING_STATUS[doc.reading_status]}</Badge>}
      {tags.slice(0, 3).map((t) => (
        <span key={t.id} className="text-caption text-muted">
          #{t.name}
        </span>
      ))}
      {tags.length > 3 && <span className="text-caption text-subtle">+{tags.length - 3}</span>}
    </div>
  )
}

export function DocTypeLabel({ type }: { type: DocumentSummary['doc_type'] }) {
  return <span className="text-caption text-subtle">{TYPE_LABELS[type]}</span>
}

function Thumbnail({ doc, className }: { doc: DocumentSummary; className?: string }) {
  const Icon = TYPE_ICONS[doc.doc_type]
  const src = doc.assets?.thumbnail
  return (
    <div
      className={cn(
        'flex items-center justify-center overflow-hidden bg-surface-muted',
        className,
      )}
    >
      {src ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover object-top dark:opacity-90"
        />
      ) : (
        <Icon className="size-8 text-subtle" aria-hidden />
      )}
    </div>
  )
}

/** Picking papers (for comparison). `reason` is why a paper can't be picked, or null. */
export interface Selection {
  selected: string[]
  toggle: (doc: DocumentSummary) => void
  reason: (doc: DocumentSummary) => string | null
}

function SelectBox({ doc, selection, className }: { doc: DocumentSummary; selection: Selection; className?: string }) {
  const reason = selection.reason(doc)
  const checked = selection.selected.includes(doc.id)
  const box = (
    <label
      className={cn(
        'flex size-8 items-center justify-center rounded-md',
        reason && !checked ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        className,
      )}
    >
      <input
        type="checkbox"
        className="size-4 cursor-[inherit] accent-primary"
        checked={checked}
        disabled={!!reason && !checked}
        onChange={() => selection.toggle(doc)}
        aria-label={`Select “${doc.title}” to compare`}
      />
    </label>
  )
  return reason && !checked ? (
    <Tooltip content={reason}>
      <span>{box}</span>
    </Tooltip>
  ) : (
    box
  )
}

export function PaperCard({ doc, selection }: { doc: DocumentSummary; selection?: Selection }) {
  const card = (
    <Link
      to={`/papers/${doc.id}`}
      className="group flex w-full flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-sm transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-md"
    >
      <Thumbnail doc={doc} className="aspect-[4/3] border-b border-border" />
      <div className="flex flex-1 flex-col p-3.5">
        <h3 className="line-clamp-2 text-small leading-snug font-semibold text-text group-hover:text-primary">
          {doc.title}
        </h3>
        <p className="mt-1 line-clamp-1 text-caption text-muted">
          {doc.authors_display || doc.original_filename}
        </p>
        <OrganizationLine doc={doc} />
        <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3">
          <StatusBadge doc={doc} />
          <DuplicateBadge doc={doc} />
          {doc.year && <Badge>{doc.year}</Badge>}
          <span className="ml-auto">
            <DocTypeLabel type={doc.doc_type} />
          </span>
        </div>
      </div>
    </Link>
  )
  if (!selection) return card
  const checked = selection.selected.includes(doc.id)
  return (
    <div className={cn('relative flex w-full rounded-lg', checked && 'ring-2 ring-primary')}>
      {card}
      <SelectBox
        doc={doc}
        selection={selection}
        className="absolute top-2 left-2 border border-border bg-surface/90 shadow-sm backdrop-blur"
      />
    </div>
  )
}

export function PaperGrid({ docs, selection }: { docs: DocumentSummary[]; selection?: Selection }) {
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {docs.map((doc) => (
        <li key={doc.id} className="flex">
          <PaperCard doc={doc} selection={selection} />
        </li>
      ))}
    </ul>
  )
}

export function PaperTable({ docs, selection }: { docs: DocumentSummary[]; selection?: Selection }) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full min-w-[720px] text-left text-small">
        <thead className="border-b border-border bg-surface-muted/60 text-caption text-muted">
          <tr>
            {selection && (
              <th className="w-10 py-2.5 pl-2">
                <span className="sr-only">Select</span>
              </th>
            )}
            <th className="px-4 py-2.5 font-medium">Paper</th>
            <th className="px-4 py-2.5 font-medium">Authors</th>
            <th className="px-4 py-2.5 font-medium">Year</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
            <th className="px-4 py-2.5 font-medium">Added</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {docs.map((doc) => (
            <tr
              key={doc.id}
              className={cn('group hover:bg-surface-muted/50', selection?.selected.includes(doc.id) && 'bg-primary-soft/40')}
            >
              {selection && (
                <td className="py-3 pl-2">
                  <SelectBox doc={doc} selection={selection} />
                </td>
              )}
              <td className="max-w-md px-4 py-3">
                <Link
                  to={`/papers/${doc.id}`}
                  className="line-clamp-1 font-medium text-text group-hover:text-primary"
                >
                  {doc.title}
                </Link>
                <div className="mt-0.5 flex items-center gap-2">
                  <DocTypeLabel type={doc.doc_type} />
                  {doc.venue && <span className="text-caption text-subtle">· {doc.venue}</span>}
                </div>
                <OrganizationLine doc={doc} />
              </td>
              <td className="max-w-56 px-4 py-3 text-muted">
                <span className="line-clamp-1">{doc.authors_display || '—'}</span>
              </td>
              <td className="px-4 py-3 text-muted tabular-nums">{doc.year ?? '—'}</td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-1.5">
                  <StatusBadge doc={doc} />
                  <DuplicateBadge doc={doc} />
                </div>
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-muted">{timeAgo(doc.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function PaperGridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" aria-busy>
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="overflow-hidden rounded-lg border border-border bg-surface">
          <Skeleton className="aspect-[4/3] rounded-none" />
          <div className="space-y-2 p-3.5">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  )
}
