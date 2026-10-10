import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, Users } from 'lucide-react'
import { TypeDot } from '@/components/knowledge/Entities'
import { Badge } from '@/components/ui/Badge'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { useDebounced } from '@/hooks/useDebounced'
import { useAuthors, useEntities } from '@/hooks/useKnowledge'
import { cn } from '@/lib/cn'
import { ENTITY_TYPES, NODE_META, authorLink, entityLink, yearsLabel } from '@/lib/knowledge'
import type { EntityType } from '@/types/api'

function SearchBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="relative w-full sm:w-72">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-subtle" aria-hidden />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={label} aria-label={label} className="pl-8" />
    </div>
  )
}

export function EntitiesView() {
  const [type, setType] = useState<EntityType>('dataset')
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState(false)
  const q = useDebounced(text.trim(), 200)
  const entities = useEntities({ type, q: q || undefined, includeMentions: mentions })
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div role="tablist" aria-label="Entity type" className="flex flex-wrap gap-1 rounded-md bg-surface-muted p-1">
          {ENTITY_TYPES.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={type === t}
              type="button"
              onClick={() => setType(t)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-small font-medium transition-colors',
                type === t ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-text',
              )}
            >
              <TypeDot type={t} /> {NODE_META[t].plural}
            </button>
          ))}
        </div>
        <SearchBox value={text} onChange={setText} label={`Search ${NODE_META[type].plural.toLowerCase()}`} />
      </div>
      <label className="flex items-center gap-2 text-small text-muted">
        <input type="checkbox" checked={mentions} onChange={(e) => setMentions(e.target.checked)} className="accent-[var(--primary)]" />
        Include ones only mentioned in passing
      </label>
      {entities.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : entities.isError ? (
        <ErrorState error={entities.error} onRetry={() => entities.refetch()} />
      ) : entities.data.length === 0 ? (
        <EmptyState
          icon={NODE_META[type].icon}
          className="rounded-lg border border-dashed border-border"
          title={q ? `No ${NODE_META[type].plural.toLowerCase()} match “${q}”` : `No ${NODE_META[type].plural.toLowerCase()} found yet`}
          description="They’re found in your papers’ text: known names from a built-in catalog, plus names your papers define or introduce."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-small">
            <thead className="bg-surface-muted text-left text-caption text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 text-right font-medium">Papers using it</th>
                <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Mentioned in</th>
                <th className="hidden px-3 py-2 font-medium md:table-cell">Years</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {entities.data.map((e) => (
                <tr key={e.id} className="hover:bg-surface-muted">
                  <td className="px-3 py-2">
                    <Link to={entityLink(e.id)} className="font-medium text-text hover:text-primary">
                      {e.name}
                    </Link>
                    {e.proposed_by > 0 && (
                      <Badge tone="primary" className="ml-2">
                        proposed here
                      </Badge>
                    )}
                    {e.source === 'discovered' && (
                      <Badge className="ml-2" title="Not in the built-in catalog: found because a paper defines or introduces it">
                        found in papers
                      </Badge>
                    )}
                    {e.aliases.length > 0 && <p className="text-caption text-subtle">also {e.aliases.slice(0, 3).join(', ')}</p>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{e.paper_count}</td>
                  <td className="hidden px-3 py-2 text-right text-muted tabular-nums sm:table-cell">{e.mention_count || '–'}</td>
                  <td className="hidden px-3 py-2 text-muted tabular-nums md:table-cell">{yearsLabel(e.first_year, e.last_year)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function AuthorsView() {
  const [text, setText] = useState('')
  const q = useDebounced(text.trim(), 200)
  const authors = useAuthors(q || undefined)
  return (
    <div className="space-y-4">
      <SearchBox value={text} onChange={setText} label="Search authors" />
      {authors.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : authors.isError ? (
        <ErrorState error={authors.error} onRetry={() => authors.refetch()} />
      ) : authors.data.length === 0 ? (
        <EmptyState
          icon={Users}
          className="rounded-lg border border-dashed border-border"
          title={q ? `No authors match “${q}”` : 'No authors yet'}
          description="Authors come from your papers’ details. If a paper’s authors are missing or wrong, fix them in its details."
        />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {authors.data.map((a) => (
            <li key={a.key}>
              <Link
                to={authorLink(a.key)}
                className="flex h-full flex-col rounded-md border border-border bg-surface p-3 transition-colors hover:border-border-strong"
              >
                <span className="font-medium text-text">{a.name}</span>
                <span className="text-small text-muted">
                  {a.paper_count} paper{a.paper_count === 1 ? '' : 's'}
                  {a.first_year ? ` · ${yearsLabel(a.first_year, a.last_year)}` : ''}
                </span>
                {a.institutions.length > 0 && <span className="mt-1 line-clamp-1 text-caption text-subtle">{a.institutions.join('; ')}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
