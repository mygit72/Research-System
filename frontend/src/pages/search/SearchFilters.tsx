import { useId, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { activeFilterCount, DOC_TYPE_LABELS, SECTION_LABELS } from '@/lib/search'
import type { FacetValue, SearchFacets, SearchFilters as Filters } from '@/types/api'

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-caption font-semibold tracking-wide text-subtle uppercase">
        {title}
      </legend>
      {children}
    </fieldset>
  )
}

function CheckList({
  options,
  selected,
  onChange,
  label,
  initial = 6,
}: {
  options: FacetValue[]
  selected: string[]
  onChange: (values: string[]) => void
  label: (value: string) => string
  initial?: number
}) {
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? options : options.slice(0, initial)
  // Keep selected values visible even when they're past the fold.
  const extra = options.filter((o) => selected.includes(o.value) && !visible.includes(o))
  return (
    <div className="space-y-1">
      {[...visible, ...extra].map((option) => (
        <label
          key={option.value}
          className="flex cursor-pointer items-center gap-2 rounded-sm py-0.5 text-small text-text"
        >
          <input
            type="checkbox"
            checked={selected.includes(option.value)}
            onChange={(e) =>
              onChange(
                e.target.checked
                  ? [...selected, option.value]
                  : selected.filter((v) => v !== option.value),
              )
            }
            className="size-4 accent-[var(--primary)]"
          />
          <span className="min-w-0 flex-1 truncate">{label(option.value)}</span>
          <span className="text-caption text-subtle tabular-nums">{option.count}</span>
        </label>
      ))}
      {options.length > initial && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-caption text-primary hover:underline"
        >
          {showAll ? 'Show fewer' : `Show all ${options.length}`}
        </button>
      )}
    </div>
  )
}

function YearRange({
  from,
  to,
  min,
  max,
  onChange,
}: {
  from?: number
  to?: number
  min: number | null
  max: number | null
  onChange: (from?: number, to?: number) => void
}) {
  const id = useId()
  // Local text state: commit on blur/Enter so typing "20" doesn't search for year 20.
  // The parent remounts this (key) when the committed years change.
  const [draft, setDraft] = useState({ from: from?.toString() ?? '', to: to?.toString() ?? '' })
  const commit = () => {
    const parse = (v: string) => (/^\d{4}$/.test(v.trim()) ? Number(v.trim()) : undefined)
    let a = parse(draft.from)
    let b = parse(draft.to)
    if (a !== undefined && b !== undefined && a > b) [a, b] = [b, a]
    if (a !== from || b !== to) onChange(a, b)
    else setDraft({ from: from?.toString() ?? '', to: to?.toString() ?? '' })
  }
  const field = (key: 'from' | 'to', label: string, placeholder: number | null) => (
    <div className="min-w-0 flex-1">
      <label htmlFor={`${id}-${key}`} className="sr-only">
        {label}
      </label>
      <Input
        id={`${id}-${key}`}
        inputMode="numeric"
        placeholder={placeholder ? String(placeholder) : label}
        value={draft[key]}
        onChange={(e) => setDraft({ ...draft, [key]: e.target.value.replace(/\D/g, '').slice(0, 4) })}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
        className="h-9"
      />
    </div>
  )
  return (
    <div className="flex items-center gap-2">
      {field('from', 'From year', min)}
      <span className="text-subtle" aria-hidden>
        –
      </span>
      {field('to', 'To year', max)}
    </div>
  )
}

export function SearchFiltersPanel({
  facets,
  filters,
  onChange,
}: {
  facets: SearchFacets
  filters: Filters
  onChange: (filters: Filters) => void
}) {
  const set = (patch: Partial<Filters>) => {
    const next = { ...filters, ...patch }
    for (const key of Object.keys(next) as (keyof Filters)[]) {
      const value = next[key]
      if (value === undefined || value === false || (Array.isArray(value) && value.length === 0))
        delete next[key]
    }
    onChange(next)
  }
  const sections = facets.section_kinds.filter((s) => s.value !== 'references')
  const active = activeFilterCount(filters)
  const collectionNames = Object.fromEntries((facets.collections ?? []).map((c) => [c.value, c.label]))
  return (
    <div className="space-y-6">
      {(facets.collections ?? []).length > 0 && (
        <Group title="Collection">
          <CheckList
            options={facets.collections}
            selected={filters.collection_ids ?? []}
            onChange={(collection_ids) => set({ collection_ids })}
            label={(v) => collectionNames[v] ?? v}
          />
        </Group>
      )}
      {(facets.tags ?? []).length > 0 && (
        <Group title="Tag">
          <CheckList
            options={facets.tags}
            selected={filters.tags ?? []}
            onChange={(tags) => set({ tags })}
            label={(v) => `#${v}`}
          />
        </Group>
      )}
      {(facets.year_min !== null || filters.year_from || filters.year_to) && (
        <Group title="Year">
          <YearRange
            key={`${filters.year_from}-${filters.year_to}`}
            from={filters.year_from}
            to={filters.year_to}
            min={facets.year_min}
            max={facets.year_max}
            onChange={(year_from, year_to) => set({ year_from, year_to })}
          />
          {(filters.year_from || filters.year_to) && (
            <p className="text-caption text-subtle">Papers without a known year are hidden.</p>
          )}
        </Group>
      )}
      {facets.doc_types.length > 1 && (
        <Group title="Document type">
          <CheckList
            options={facets.doc_types}
            selected={filters.doc_types ?? []}
            onChange={(doc_types) => set({ doc_types })}
            label={(v) => DOC_TYPE_LABELS[v] ?? v}
          />
        </Group>
      )}
      {facets.authors.length > 0 && (
        <Group title="Author">
          <CheckList
            options={facets.authors}
            selected={filters.authors ?? []}
            onChange={(authors) => set({ authors })}
            label={(v) => v}
          />
        </Group>
      )}
      {sections.length > 0 && (
        <Group title="Section">
          <CheckList
            options={sections}
            selected={filters.section_kinds ?? []}
            onChange={(section_kinds) => set({ section_kinds })}
            label={(v) => SECTION_LABELS[v] ?? v}
          />
        </Group>
      )}
      <Group title="Also search">
        <label className="flex cursor-pointer items-start gap-2 text-small text-text">
          <input
            type="checkbox"
            checked={!!filters.include_references}
            onChange={(e) => set({ include_references: e.target.checked })}
            className="mt-0.5 size-4 accent-[var(--primary)]"
          />
          <span>
            Reference lists
            <span className="block text-caption text-muted">
              Off by default: citations match names and titles without answering anything.
            </span>
          </span>
        </label>
      </Group>
      {active > 0 && (
        <Button variant="secondary" size="sm" className="w-full" onClick={() => onChange({})}>
          Clear {active} filter{active === 1 ? '' : 's'}
        </Button>
      )}
    </div>
  )
}
