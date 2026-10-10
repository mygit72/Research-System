import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Input } from '@/components/ui/Input'
import { useDebounced } from '@/hooks/useDebounced'
import { documentsApi } from '@/services/api'
import type { DocumentStatus, DocumentSummary } from '@/types/api'

/** Search the library and pick a paper. `reason` explains why a paper can't be picked. */
export function PaperPicker({
  picked,
  onAdd,
  reason = () => null,
  disabled,
  statuses = ['ready'],
  placeholder = 'Add a paper by title or author…',
}: {
  picked: string[]
  onAdd: (doc: DocumentSummary) => void
  reason?: (doc: DocumentSummary) => string | null
  disabled?: boolean
  statuses?: DocumentStatus[]
  placeholder?: string
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const q = useDebounced(query.trim())
  const results = useQuery({
    queryKey: ['documents', 'list', { q, statuses, limit: 20, picker: true }],
    queryFn: () => documentsApi.list({ q: q || undefined, status: statuses, limit: 20 }),
    enabled: open,
  })
  const options = (results.data?.items ?? []).filter((d) => !picked.includes(d.id))
  return (
    <div className="relative">
      <Input
        type="search"
        placeholder={placeholder}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        aria-label="Find a paper to add"
        disabled={disabled}
      />
      {open && (
        <ul
          role="listbox"
          aria-label="Papers"
          className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-border bg-surface-elevated p-1 shadow-lg"
        >
          {results.isPending ? (
            <li className="px-3 py-2 text-small text-muted">Loading…</li>
          ) : options.length === 0 ? (
            <li className="px-3 py-2 text-small text-muted">No more papers match.</li>
          ) : (
            options.map((doc) => {
              const why = reason(doc)
              return (
                <li key={doc.id} role="option" aria-selected={false} aria-disabled={!!why}>
                  <button
                    type="button"
                    disabled={!!why}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      onAdd(doc)
                      setQuery('')
                    }}
                    className="flex w-full flex-col items-start rounded-sm px-3 py-2 text-left hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span className="line-clamp-1 text-small font-medium text-text">{doc.title}</span>
                    <span className="text-caption text-muted">
                      {why ?? [doc.authors_display, doc.year].filter(Boolean).join(' · ')}
                    </span>
                  </button>
                </li>
              )
            })
          )}
        </ul>
      )}
    </div>
  )
}
