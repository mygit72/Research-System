import { useMutation } from '@tanstack/react-query'
import { BookOpenText, Bookmark as BookmarkIcon, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { refreshOrganization, useBookmarks } from '@/hooks/useOrganization'
import { timeAgo } from '@/lib/format'
import { bookmarksApi } from '@/services/api'
import { BOOKMARK_KINDS, anchorLink } from '@/lib/organization'
import type { Bookmark, BookmarkKind } from '@/types/api'

function BookmarkItem({
  bookmark,
  showPaper,
  onOpen,
}: {
  bookmark: Bookmark
  showPaper?: boolean
  onOpen?: (bookmark: Bookmark) => void
}) {
  const remove = useMutation({
    mutationFn: () => bookmarksApi.remove(bookmark.id),
    onSuccess: () => {
      toast.success('Bookmark removed')
      refreshOrganization()
    },
    onError: (e) => toast.error(e.message),
  })
  const target = bookmark.target
  const title = bookmark.label || (bookmark.kind === 'paper' ? bookmark.document_title : target.quote) || 'Bookmark'
  return (
    <li className="flex items-start gap-3 px-3 py-2.5">
      <BookmarkIcon className="mt-0.5 size-4 shrink-0 fill-primary/20 text-primary" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-small text-text">{title}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-caption text-muted">
          <Badge>{BOOKMARK_KINDS[bookmark.kind]}</Badge>
          {showPaper && bookmark.kind !== 'paper' && <span className="line-clamp-1">{bookmark.document_title}</span>}
          {target.page && <span>p. {target.page}</span>}
          <span>{timeAgo(bookmark.created_at)}</span>
        </p>
      </div>
      {onOpen ? (
        <Button variant="ghost" size="sm" className="h-7 px-2 text-caption" onClick={() => onOpen(bookmark)}>
          <BookOpenText className="size-3.5" aria-hidden /> Show
        </Button>
      ) : (
        <Link
          to={anchorLink(bookmark.document_id, target)}
          state={{ boxes: target.boxes }}
          className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-caption font-medium text-primary hover:bg-surface-muted"
        >
          <BookOpenText className="size-3.5" aria-hidden /> Open
        </Link>
      )}
      <Button variant="ghost" size="icon-sm" aria-label="Remove bookmark" onClick={() => remove.mutate()}>
        <Trash2 className="size-3.5" />
      </Button>
    </li>
  )
}

export function BookmarksList({
  documentId,
  kinds,
  showPaper,
  onOpen,
  emptyHint,
}: {
  documentId?: string
  kinds?: BookmarkKind[]
  showPaper?: boolean
  onOpen?: (bookmark: Bookmark) => void
  emptyHint?: string
}) {
  const bookmarks = useBookmarks({ documentId, kinds })
  if (bookmarks.isPending) return <Skeleton className="h-16 w-full" />
  if (bookmarks.isError) return <ErrorState error={bookmarks.error} onRetry={() => bookmarks.refetch()} />
  if (!bookmarks.data.length)
    return (
      <EmptyState
        icon={BookmarkIcon}
        className="py-8"
        title="No bookmarks yet"
        description={emptyHint ?? 'Bookmark papers, passages, figures, tables and chat citations to find them again.'}
      />
    )
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
      {bookmarks.data.map((b) => (
        <BookmarkItem key={b.id} bookmark={b} showPaper={showPaper} onOpen={onOpen} />
      ))}
    </ul>
  )
}
