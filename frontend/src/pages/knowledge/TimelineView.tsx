import { useSearchParams } from 'react-router-dom'
import { CalendarRange, Sparkles } from 'lucide-react'
import { EntityChip, PaperLine } from '@/components/knowledge/Entities'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { useTimeline } from '@/hooks/useKnowledge'
import { cn } from '@/lib/cn'
import type { TimelineFilters, TimelinePaper } from '@/types/api'

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-caption font-medium text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-full min-w-0 rounded-md border border-border bg-surface px-2 text-small text-text sm:w-48"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function PaperItem({ paper }: { paper: TimelinePaper }) {
  return (
    <li className="rounded-md border border-border bg-surface p-3">
      <PaperLine paper={paper}>
        {(paper.proposes.length > 0 || paper.uses.length > 0) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {paper.proposes.map((e) => (
              <EntityChip key={e.id} entity={e} emphasis />
            ))}
            {paper.uses.map((e) => (
              <EntityChip key={e.id} entity={e} />
            ))}
          </div>
        )}
        {paper.topic && <p className="mt-1.5 text-caption text-subtle">Topic: {paper.topic.name}</p>}
      </PaperLine>
    </li>
  )
}

export function TimelineView() {
  const [params, setParams] = useSearchParams()
  const filters: TimelineFilters = {
    topic: params.get('topic') ? Number(params.get('topic')) : undefined,
    author: params.get('author') ?? undefined,
    venue: params.get('venue') ?? undefined,
    entityId: params.get('entity') ?? undefined,
  }
  const timeline = useTimeline(filters)
  const set = (key: string, value: string) =>
    setParams((p) => {
      if (value) p.set(key, value)
      else p.delete(key)
      return p
    })

  if (timeline.isPending) return <Skeleton className="h-96 w-full" />
  if (timeline.isError) return <ErrorState error={timeline.error} onRetry={() => timeline.refetch()} />
  const { years, undated, filters: options } = timeline.data
  const filtered = Object.values(filters).some((v) => v !== undefined)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label="Topic"
          value={params.get('topic') ?? ''}
          onChange={(v) => set('topic', v)}
          options={options.topics.map((t) => ({ value: String(t.id), label: `${t.name} (${t.size})` }))}
        />
        <Select
          label="Method or model"
          value={params.get('entity') ?? ''}
          onChange={(v) => set('entity', v)}
          options={options.methods.map((m) => ({ value: m.id, label: `${m.name} (${m.papers})` }))}
        />
        <Select
          label="Author"
          value={params.get('author') ?? ''}
          onChange={(v) => set('author', v)}
          options={options.authors.map((a) => ({ value: a.key, label: `${a.name} (${a.papers})` }))}
        />
        <Select
          label="Venue"
          value={params.get('venue') ?? ''}
          onChange={(v) => set('venue', v)}
          options={options.venues.map((v) => ({ value: v.name, label: `${v.name} (${v.papers})` }))}
        />
        {filtered && (
          <Button
            variant="ghost"
            onClick={() =>
              setParams((p) => {
                for (const key of ['topic', 'entity', 'author', 'venue']) p.delete(key)
                return p
              })
            }
          >
            Clear filters
          </Button>
        )}
      </div>
      {options.topics.length === 0 && (
        <p className="text-caption text-subtle">Topic filters appear once you’ve grouped your papers on the Topics tab.</p>
      )}

      {years.length === 0 && undated.length === 0 ? (
        <EmptyState
          icon={CalendarRange}
          className="rounded-lg border border-dashed border-border"
          title={filtered ? 'No papers match these filters' : 'No papers yet'}
          description={filtered ? 'Try removing a filter.' : 'Papers appear here by publication year once they’re processed.'}
        />
      ) : (
        <ol className="relative space-y-8 border-l-2 border-border pl-6">
          {years.map((year) => (
            <li key={year.year} className="relative">
              <span
                aria-hidden
                className="absolute top-1.5 -left-[33px] size-4 rounded-full border-2 border-primary bg-surface"
              />
              <h2 className="text-h3 text-text tabular-nums">
                {year.year}
                <span className="ml-2 text-small font-normal text-subtle">
                  {year.papers.length} paper{year.papers.length === 1 ? '' : 's'}
                </span>
              </h2>
              {year.first_seen.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="inline-flex items-center gap-1 text-caption text-subtle">
                    <Sparkles className="size-3.5" aria-hidden /> First seen in your library:
                  </span>
                  {year.first_seen.map((e) => (
                    <EntityChip key={e.id} entity={e} />
                  ))}
                </div>
              )}
              <ul className={cn('mt-3 grid gap-2', year.papers.length > 1 && 'lg:grid-cols-2')}>
                {year.papers.map((paper) => (
                  <PaperItem key={paper.id} paper={paper} />
                ))}
              </ul>
            </li>
          ))}
          {undated.length > 0 && (
            <li className="relative">
              <span aria-hidden className="absolute top-1.5 -left-[33px] size-4 rounded-full border-2 border-border bg-surface" />
              <h2 className="text-h3 text-text">No year</h2>
              <p className="text-small text-muted">Add the year in a paper’s details to place it on the timeline.</p>
              <ul className="mt-3 grid gap-2 lg:grid-cols-2">
                {undated.map((paper) => (
                  <PaperItem key={paper.id} paper={paper} />
                ))}
              </ul>
            </li>
          )}
        </ol>
      )}
      <p className="text-caption text-subtle">
        Highlighted chips are what a paper proposes; the others are what it uses. “First seen” means first in your
        library, not in the field.
      </p>
    </div>
  )
}
