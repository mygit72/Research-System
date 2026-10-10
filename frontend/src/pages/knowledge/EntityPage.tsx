import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, BookMarked, CalendarRange, Info, Network } from 'lucide-react'
import { EntityChip, EvidenceList, PaperLine, TypeDot } from '@/components/knowledge/Entities'
import { Badge } from '@/components/ui/Badge'
import { buttonClass } from '@/lib/buttonStyles'
import { Card } from '@/components/ui/Card'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'
import { useEntity } from '@/hooks/useKnowledge'
import { ENTITY_RELATION_HELP, ENTITY_RELATION_LABELS, NODE_META, graphFocusLink } from '@/lib/knowledge'
import type { EntityRelation } from '@/types/api'

const INFO_LABELS: Record<string, string> = {
  task: 'Task',
  domain: 'Domain',
  size: 'Size',
  license: 'License',
}

function YearBars({ years }: { years: { year: number; papers: number }[] }) {
  if (years.length < 2) return null
  const max = Math.max(...years.map((y) => y.papers))
  return (
    <div>
      <h2 className="mb-2 text-small font-semibold text-text">Papers using it, by year</h2>
      <ul className="flex items-end gap-1.5" aria-label="Papers by year">
        {years.map((y) => (
          <li key={y.year} className="flex flex-col items-center gap-1">
            <span className="text-caption text-muted tabular-nums">{y.papers}</span>
            <span className="w-6 rounded-sm bg-primary" style={{ height: `${8 + (y.papers / max) * 48}px` }} aria-hidden />
            <span className="text-caption text-subtle tabular-nums">{y.year}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function EntityPage() {
  const { id = '' } = useParams()
  const entity = useEntity(id)
  if (entity.isPending)
    return (
      <PageContainer>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="mt-6 h-64 w-full" />
      </PageContainer>
    )
  if (entity.isError)
    return (
      <PageContainer>
        <ErrorState error={entity.error} onRetry={() => entity.refetch()} />
      </PageContainer>
    )
  const e = entity.data
  const meta = NODE_META[e.type]
  const groups = (['proposes', 'uses', 'mentions'] as EntityRelation[])
    .map((relation) => ({ relation, papers: e.papers.filter((p) => p.relation === relation) }))
    .filter((g) => g.papers.length)
  const infoRows = Object.entries(e.info).filter(([key]) => INFO_LABELS[key])

  return (
    <PageContainer>
      <Link to="/graph?view=entities" className="inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-3.5" aria-hidden /> Datasets & methods
      </Link>
      <header className="mt-3 mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-small text-muted">
            <TypeDot type={e.type} /> {meta.label}
            {e.source === 'discovered' && <Badge>found in your papers</Badge>}
          </p>
          <h1 className="mt-1 text-h1 text-balance text-text">{e.name}</h1>
          {e.aliases.length > 0 && <p className="mt-1 text-small text-muted">Also written as {e.aliases.join(', ')}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Link to={`/graph?view=timeline&entity=${e.id}`} className={buttonClass('secondary', 'sm')}>
            <CalendarRange className="size-3.5" aria-hidden /> Timeline
          </Link>
          <Link to={graphFocusLink(`entity:${e.id}`)} className={buttonClass('secondary', 'sm')}>
            <Network className="size-3.5" aria-hidden /> In the graph
          </Link>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-6">
          {groups.map((group) => (
            <section key={group.relation}>
              <h2 className="text-h3 text-text">
                {ENTITY_RELATION_LABELS[group.relation]} it
                <span className="ml-2 text-small font-normal text-subtle">
                  {group.papers.length} paper{group.papers.length === 1 ? '' : 's'}
                </span>
              </h2>
              <p className="mb-3 text-caption text-subtle">{ENTITY_RELATION_HELP[group.relation]}</p>
              <ul className="space-y-3">
                {group.papers.map((paper) => (
                  <li key={paper.id}>
                    <Card className="p-4">
                      <PaperLine paper={paper}>
                        <p className="mt-1 text-caption text-subtle">
                          {paper.mentions} mention{paper.mentions === 1 ? '' : 's'}
                          {paper.variants.length > 0 && ` · as ${paper.variants.join(', ')}`}
                        </p>
                        <div className="mt-3">
                          <EvidenceList documentId={paper.id} evidence={paper.evidence} />
                        </div>
                      </PaperLine>
                    </Card>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <aside className="space-y-6">
          {infoRows.length > 0 && (
            <Card className="p-4">
              <h2 className="flex items-center gap-1.5 text-small font-semibold text-text">
                <BookMarked className="size-4 text-subtle" aria-hidden /> Reference information
              </h2>
              <dl className="mt-2 space-y-2 text-small">
                {infoRows.map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-caption text-subtle">{INFO_LABELS[key]}</dt>
                    <dd className="text-text">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 flex gap-1.5 text-caption text-subtle">
                <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                From the app’s built-in catalog of well-known {meta.plural.toLowerCase()}, not from your papers. Check
                the official page before citing it.
              </p>
            </Card>
          )}
          <YearBars years={e.years} />
          {e.related.length > 0 && (
            <div>
              <h2 className="mb-2 text-small font-semibold text-text">Often used together</h2>
              <div className="flex flex-wrap gap-1.5">
                {e.related.map((r) => (
                  <EntityChip key={r.id} entity={r} count={r.shared_papers} />
                ))}
              </div>
              <p className="mt-2 text-caption text-subtle">Number = papers in your library that use both.</p>
            </div>
          )}
        </aside>
      </div>
    </PageContainer>
  )
}
