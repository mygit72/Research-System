import { useId, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { useSetTags, useTags } from '@/hooks/useOrganization'
import { cn } from '@/lib/cn'
import type { TagRef } from '@/types/api'

export function TagChip({ tag, onRemove, className }: { tag: Pick<TagRef, 'name'>; onRemove?: () => void; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1 rounded-full border border-border bg-surface-muted px-2 text-caption text-text',
        className,
      )}
    >
      <span className="text-subtle" aria-hidden>
        #
      </span>
      {tag.name}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove tag ${tag.name}`}
          className="-mr-1 rounded-full p-0.5 text-subtle hover:bg-surface hover:text-text"
        >
          <X className="size-3" />
        </button>
      )}
    </span>
  )
}

/** A paper's tags: chips, an input with suggestions from the user's other tags. */
export function TagEditor({ documentId, tags }: { documentId: string; tags: TagRef[] }) {
  const all = useTags()
  const save = useSetTags(documentId)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const listId = useId()
  const names = tags.map((t) => t.name)
  const add = (raw: string) => {
    const name = raw.replace(/^#/, '').trim()
    setDraft('')
    if (!name || names.some((n) => n.toLowerCase() === name.toLowerCase())) return
    save.mutate([...names, name])
  }
  const suggestions = (all.data ?? []).filter((t) => !names.some((n) => n.toLowerCase() === t.name.toLowerCase()))
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Tags">
      {tags.map((tag) => (
        <TagChip key={tag.id} tag={tag} onRemove={() => save.mutate(names.filter((n) => n !== tag.name))} />
      ))}
      {adding ? (
        <>
          <input
            autoFocus
            value={draft}
            list={listId}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault()
                add(draft)
              }
              if (e.key === 'Escape') setAdding(false)
              if (e.key === 'Backspace' && !draft && names.length) save.mutate(names.slice(0, -1))
            }}
            onBlur={() => {
              add(draft)
              setAdding(false)
            }}
            placeholder="Add tag…"
            aria-label="New tag"
            maxLength={60}
            className="h-6 w-32 rounded-full border border-border bg-surface px-2 text-caption text-text placeholder:text-subtle focus-visible:border-primary focus-visible:outline-none"
          />
          <datalist id={listId}>
            {suggestions.map((t) => (
              <option key={t.id} value={t.name} />
            ))}
          </datalist>
        </>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex h-6 items-center gap-1 rounded-full border border-dashed border-border-strong px-2 text-caption text-muted hover:border-primary hover:text-primary"
        >
          <Plus className="size-3" aria-hidden /> {tags.length ? 'Tag' : 'Add tag'}
        </button>
      )}
    </div>
  )
}

