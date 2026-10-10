import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { BookOpenText, NotebookPen, Pencil, Plus, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Markdown } from '@/components/chat/Markdown'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { refreshOrganization, useCreateNote, useNotes } from '@/hooks/useOrganization'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { notesApi } from '@/services/api'
import type { Anchor, Note } from '@/types/api'

const plainCite = (_: number[], raw: string, key: string) => <span key={key}>{raw}</span>

export function NoteText({ content }: { content: string }) {
  return (
    <div className="text-small leading-relaxed text-text">
      <Markdown text={content} renderCite={plainCite} />
    </div>
  )
}

/** Markdown textarea with a preview; Ctrl/⌘+Enter saves. */
export function NoteEditor({
  initial = '',
  saving,
  onSave,
  onCancel,
  autoFocus = true,
}: {
  initial?: string
  saving?: boolean
  onSave: (content: string) => void
  onCancel?: () => void
  autoFocus?: boolean
}) {
  const [content, setContent] = useState(initial)
  const [preview, setPreview] = useState(false)
  const empty = !content.trim()
  return (
    <div className="rounded-md border border-border bg-surface">
      <div className="flex gap-1 border-b border-border px-2 py-1" role="tablist" aria-label="Note editor">
        {(['Write', 'Preview'] as const).map((label) => (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={(label === 'Preview') === preview}
            onClick={() => setPreview(label === 'Preview')}
            className={cn(
              'rounded-sm px-2 py-1 text-caption font-medium',
              (label === 'Preview') === preview ? 'bg-surface-muted text-text' : 'text-muted hover:text-text',
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto self-center text-caption text-subtle">Markdown</span>
      </div>
      {preview ? (
        <div className="min-h-28 px-3 py-2">
          {empty ? <p className="text-small text-subtle">Nothing to preview.</p> : <NoteText content={content} />}
        </div>
      ) : (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !empty) onSave(content.trim())
          }}
          autoFocus={autoFocus}
          rows={5}
          aria-label="Note"
          placeholder="Write a note… **bold**, *italic*, lists and `code` work."
          className="block w-full resize-y bg-transparent px-3 py-2 text-small text-text placeholder:text-subtle focus-visible:outline-none"
        />
      )}
      <div className="flex justify-end gap-2 border-t border-border px-2 py-1.5">
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button size="sm" onClick={() => onSave(content.trim())} disabled={empty} loading={saving}>
          Save note
        </Button>
      </div>
    </div>
  )
}

export function AnchorQuote({ anchor, onOpen }: { anchor: Anchor; onOpen?: () => void }) {
  if (!anchor.quote && !anchor.page) return null
  return (
    <div className="mb-2 flex items-start gap-2 rounded-sm border-l-2 border-primary/50 bg-surface-muted/60 px-2.5 py-1.5">
      <div className="min-w-0 flex-1">
        {anchor.quote && <p className="line-clamp-3 text-caption text-muted italic">“{anchor.quote}”</p>}
        <p className="mt-0.5 text-caption text-subtle">
          {[anchor.type === 'citation' ? 'Chat citation' : null, anchor.page ? `p. ${anchor.page}` : null, anchor.section_title]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </div>
      {onOpen && (
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex shrink-0 items-center gap-1 text-caption font-medium text-primary hover:underline"
        >
          <BookOpenText className="size-3.5" aria-hidden /> Show
        </button>
      )}
    </div>
  )
}

function NoteItem({ note, onOpenAnchor, showPaper }: { note: Note; onOpenAnchor?: (note: Note) => void; showPaper?: boolean }) {
  const [editing, setEditing] = useState(false)
  const update = useMutation({
    mutationFn: (content: string) => notesApi.update(note.id, content),
    onSuccess: () => {
      setEditing(false)
      refreshOrganization()
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => notesApi.remove(note.id),
    onSuccess: () => {
      toast.success('Note deleted')
      refreshOrganization()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <li className="rounded-lg border border-border bg-surface p-3">
      {showPaper && (note.document_id || note.collection_id) && (
        <Link
          to={note.document_id ? `/papers/${note.document_id}?tab=notes` : `/collections/${note.collection_id}`}
          className="mb-1.5 line-clamp-1 text-caption font-medium text-text hover:text-primary"
        >
          {note.document_title ?? 'Collection note'}
        </Link>
      )}
      {note.anchor && note.anchor.type !== 'paper' && (
        <AnchorQuote anchor={note.anchor} onOpen={onOpenAnchor && (() => onOpenAnchor(note))} />
      )}
      {editing ? (
        <NoteEditor initial={note.content} saving={update.isPending} onSave={(c) => update.mutate(c)} onCancel={() => setEditing(false)} />
      ) : (
        <NoteText content={note.content} />
      )}
      {!editing && (
        <div className="mt-2 flex items-center gap-1 text-caption text-subtle">
          <span className="flex-1">{note.updated_at !== note.created_at ? 'Edited ' : ''}{timeAgo(note.updated_at)}</span>
          <Button variant="ghost" size="icon-sm" aria-label="Edit note" onClick={() => setEditing(true)}>
            <Pencil className="size-3.5" />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Delete note" onClick={() => remove.mutate()}>
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      )}
    </li>
  )
}

/** Notes of a paper or a collection, newest first, with a composer on top. */
export function NotesList({
  documentId,
  collectionId,
  onOpenAnchor,
  showPaper,
  composer = true,
}: {
  documentId?: string
  collectionId?: string
  onOpenAnchor?: (note: Note) => void
  showPaper?: boolean
  /** Library-wide lists have no composer: notes are written on a paper or collection. */
  composer?: boolean
}) {
  const notes = useNotes({ documentId, collectionId })
  const create = useCreateNote()
  const [composing, setComposing] = useState(false)
  return (
    <div className="space-y-3">
      {composing ? (
        <NoteEditor
          saving={create.isPending}
          onCancel={() => setComposing(false)}
          onSave={(content) =>
            create.mutate(
              { content, document_id: documentId, collection_id: collectionId, anchor: documentId ? { type: 'paper' } : undefined },
              { onSuccess: () => setComposing(false) },
            )
          }
        />
      ) : (
        composer && (
          <Button variant="secondary" size="sm" onClick={() => setComposing(true)}>
            <Plus className="size-4" aria-hidden /> Add note
          </Button>
        )
      )}
      {notes.isPending ? (
        <Skeleton className="h-20 w-full" />
      ) : notes.isError ? (
        <ErrorState error={notes.error} onRetry={() => notes.refetch()} />
      ) : notes.data.length === 0 ? (
        !composing && (
          <EmptyState
            icon={NotebookPen}
            className="py-8"
            title="No notes yet"
            description={
              documentId
                ? 'Write notes about this paper, or click a passage in the reader to note or bookmark it.'
                : collectionId
                  ? 'Keep project notes here: scope, open questions, what to read next.'
                  : 'Write notes on a paper (its Notes tab, or by clicking a passage in the reader) or on a collection.'
            }
          />
        )
      ) : (
        <ul className="space-y-3">
          {notes.data.map((note) => (
            <NoteItem key={note.id} note={note} onOpenAnchor={onOpenAnchor} showPaper={showPaper} />
          ))}
        </ul>
      )}
    </div>
  )
}

/** "Add note" for a passage, figure, table or citation. */
export function NoteDialog({
  open,
  onOpenChange,
  documentId,
  anchor,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  documentId: string
  anchor: Anchor
}) {
  const create = useCreateNote()
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add a note" className="max-w-lg">
      <AnchorQuote anchor={anchor} />
      <NoteEditor
        saving={create.isPending}
        onCancel={() => onOpenChange(false)}
        onSave={(content) =>
          create.mutate({ content, document_id: documentId, anchor }, { onSuccess: () => onOpenChange(false) })
        }
      />
    </Dialog>
  )
}
