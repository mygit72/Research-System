import { useState } from 'react'
import { Bookmark, NotebookPen } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Tooltip } from '@/components/ui/Tooltip'
import { useCreateBookmark } from '@/hooks/useOrganization'
import { cn } from '@/lib/cn'
import { BOOKMARK_KINDS } from '@/lib/organization'
import type { Anchor, BookmarkKind } from '@/types/api'
import { NoteDialog } from './Notes'

/** Bookmark / add a note to something in a paper: a passage, figure, table or citation. */
export function SaveActions({
  documentId,
  kind,
  target,
  label = '',
  compact,
  className,
}: {
  documentId: string
  kind: Exclude<BookmarkKind, 'paper'>
  target: Anchor
  label?: string
  /** Icon-only buttons (cards, popovers). */
  compact?: boolean
  className?: string
}) {
  const bookmark = useCreateBookmark()
  const [noting, setNoting] = useState(false)
  const what = BOOKMARK_KINDS[kind].toLowerCase()
  const anchor: Anchor = { ...target, type: kind === 'citation' ? 'citation' : 'passage' }
  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <Tooltip content={`Bookmark this ${what}`}>
        <Button
          variant="ghost"
          size={compact ? 'icon-sm' : 'sm'}
          className={cn(!compact && 'h-7 px-2 text-caption')}
          aria-label={`Bookmark this ${what}`}
          loading={bookmark.isPending}
          onClick={() => bookmark.mutate({ document_id: documentId, kind, target, label })}
        >
          {!bookmark.isPending && <Bookmark className="size-3.5" aria-hidden />}
          {!compact && 'Bookmark'}
        </Button>
      </Tooltip>
      <Tooltip content={`Add a note to this ${what}`}>
        <Button
          variant="ghost"
          size={compact ? 'icon-sm' : 'sm'}
          className={cn(!compact && 'h-7 px-2 text-caption')}
          aria-label={`Add a note to this ${what}`}
          onClick={() => setNoting(true)}
        >
          <NotebookPen className="size-3.5" aria-hidden />
          {!compact && 'Note'}
        </Button>
      </Tooltip>
      {noting && <NoteDialog open={noting} onOpenChange={setNoting} documentId={documentId} anchor={anchor} />}
    </span>
  )
}
