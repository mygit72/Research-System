import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, CalendarRange, Info, Network } from 'lucide-react'
import { EntityChip, PaperLine } from '@/components/knowledge/Entities'
import { buttonClass } from '@/lib/buttonStyles'
import { Card } from '@/components/ui/Card'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'
import { useAuthor } from '@/hooks/useKnowledge'
import { authorLink, graphFocusLink, yearsLabel } from '@/lib/knowledge'

export function AuthorPage() {
  const { key = '' } = useParams()
  const author = useAuthor(key)
  if (author.isPending)
    return (
      <PageContainer>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="mt-6 h-64 w-full" />
      </PageContainer>
    )
  if (author.isError)
    return (
      <PageContainer>
        <ErrorState error={author.error} onRetry={() => author.refetch()} />
      </PageContainer>
    )
  const a = author.data
  const first = a.years[0]?.year ?? null
  const last = a.years.at(-1)?.year ?? null
  return (
    <PageContainer>
      <Link to="/graph?view=authors" className="inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-3.5" aria-hidden /> Authors
      </Link>
      <header className="mt-3 mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-h1 text-balance text-text">{a.name}</h1>
          <p className="mt-1 text-small text-muted">
            {a.paper_count} paper{a.paper_count === 1 ? '' : 's'} in your library
            {first ? ` · ${yearsLabel(first, last)}` : ''}
            {a.institutions.length > 0 && ` · ${a.institutions.join('; ')}`}
          </p>
          {a.spellings.length > 1 && <p className="mt-1 text-caption text-subtle">Listed as {a.spellings.join(', ')}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Link to={`/graph?view=timeline&author=${encodeURIComponent(a.key)}`} className={buttonClass('secondary', 'sm')}>
            <CalendarRange className="size-3.5" aria-hidden /> Timeline
          </Link>
          <Link to={graphFocusLink(`author:${a.key}`)} className={buttonClass('secondary', 'sm')}>
            <Network className="size-3.5" aria-hidden /> In the graph
          </Link>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <section>
          <h2 className="mb-3 text-h3 text-text">Papers</h2>
          <ul className="space-y-3">
            {a.papers.map((paper) => (
              <li key={paper.id}>
                <Card className="p-4">
                  <PaperLine paper={paper}>
                    {paper.topic && <p className="mt-1 text-caption text-subtle">Topic: {paper.topic.name}</p>}
                  </PaperLine>
                </Card>
              </li>
            ))}
          </ul>
        </section>
        <aside className="space-y-6">
          {a.coauthors.length > 0 && (
            <div>
              <h2 className="mb-2 text-small font-semibold text-text">Co-authors</h2>
              <ul className="space-y-1">
                {a.coauthors.map((c) => (
                  <li key={c.key} className="flex items-center justify-between gap-2 text-small">
                    <Link to={authorLink(c.key)} className="truncate text-text hover:text-primary">
                      {c.name}
                    </Link>
                    <span className="text-caption text-subtle tabular-nums">
                      {c.shared_papers} paper{c.shared_papers === 1 ? '' : 's'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {a.topics.length > 0 && (
            <div>
              <h2 className="mb-2 text-small font-semibold text-text">Topics</h2>
              <ul className="space-y-1 text-small text-muted">
                {a.topics.map((t) => (
                  <li key={t.name}>
                    {t.name} <span className="text-caption text-subtle">({t.papers})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {a.entities.length > 0 && (
            <div>
              <h2 className="mb-2 text-small font-semibold text-text">Datasets, models & methods used</h2>
              <div className="flex flex-wrap gap-1.5">
                {a.entities.map((e) => (
                  <EntityChip key={e.id} entity={e} count={e.papers} />
                ))}
              </div>
            </div>
          )}
          {a.keywords.length > 0 && (
            <div>
              <h2 className="mb-2 text-small font-semibold text-text">Keywords</h2>
              <p className="text-small text-muted">{a.keywords.join(', ')}</p>
            </div>
          )}
          <p className="flex gap-1.5 text-caption text-subtle">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Only what your papers document: their author lists, affiliations and years. Nothing here rates the
            researcher.
          </p>
        </aside>
      </div>
    </PageContainer>
  )
}
