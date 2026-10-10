import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowUpRight, ChevronDown, Network, Users } from 'lucide-react'
import { EntityChip, EvidenceList, PaperLine, TypeDot } from '@/components/knowledge/Entities'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/Card'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Tooltip } from '@/components/ui/Tooltip'
import { useDocumentEntities, useRelatedWork } from '@/hooks/useKnowledge'
import { ENTITY_RELATION_HELP, ENTITY_RELATION_LABELS, NODE_META, graphFocusLink } from '@/lib/knowledge'
import type { DocumentEntity, EntityRelation, EntityType } from '@/types/api'

/** Overview card: what the paper proposes and uses, with the sentences that say so. */
export function PaperEntitiesCard({ documentId, ready }: { documentId: string; ready: boolean }) {
  const entities = useDocumentEntities(documentId, ready)
  const [open, setOpen] = useState<string | null>(null)
  if (!ready) return null
  if (entities.isPending) return <Skeleton className="h-32 w-full" />
  if (entities.isError) return <ErrorState error={entities.error} onRetry={() => entities.refetch()} />
  const rows = entities.data
  if (rows.length === 0) return null
  const groups = (['proposes', 'uses'] as EntityRelation[])
    .map((relation) => ({ relation, items: rows.filter((r) => r.relation === relation) }))
    .filter((g) => g.items.length)
  const mentions = rows.filter((r) => r.relation === 'mentions')
  const selected: DocumentEntity | undefined = rows.find((r) => r.id === open)
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>Datasets, models & methods</CardTitle>
        <Link to={graphFocusLink(`paper:${documentId}`)} className="inline-flex items-center gap-1 text-caption text-primary hover:underline">
          <Network className="size-3.5" aria-hidden /> In the graph
        </Link>
      </CardHeader>
      <CardBody className="space-y-4">
        {groups.map((group) => (
          <div key={group.relation}>
            <Tooltip content={ENTITY_RELATION_HELP[group.relation]}>
              <h3 className="mb-1.5 inline-block text-caption font-medium text-subtle underline decoration-dotted underline-offset-2">
                {ENTITY_RELATION_LABELS[group.relation]}
              </h3>
            </Tooltip>
            <ul className="flex flex-wrap gap-1.5">
              {group.items.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    aria-expanded={open === e.id}
                    onClick={() => setOpen(open === e.id ? null : e.id)}
                    className={
                      'inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-caption font-medium transition-colors ' +
                      (open === e.id
                        ? 'border-primary bg-primary-soft text-primary'
                        : group.relation === 'proposes'
                          ? 'border-transparent bg-primary-soft text-primary hover:border-primary'
                          : 'border-border bg-surface text-text hover:border-border-strong')
                    }
                  >
                    <TypeDot type={e.type} />
                    {e.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {selected && (
          <div className="rounded-md border border-border bg-surface-muted/50 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <EntityChip entity={selected} />
              <span className="text-caption text-subtle">
                {NODE_META[selected.type].label} · {selected.mentions} mention{selected.mentions === 1 ? '' : 's'} here ·
                used by {selected.paper_count} paper{selected.paper_count === 1 ? '' : 's'} in your library
              </span>
            </div>
            <EvidenceList documentId={documentId} evidence={selected.evidence} />
          </div>
        )}
        {mentions.length > 0 && (
          <p className="text-caption text-subtle">
            Also mentioned in passing: {mentions.slice(0, 12).map((m) => m.name).join(', ')}
            {mentions.length > 12 ? ` and ${mentions.length - 12} more` : ''}.
          </p>
        )}
      </CardBody>
    </Card>
  )
}

const SHARED_LABELS: Record<EntityType, string> = {
  dataset: 'datasets',
  model: 'models',
  method: 'methods',
  task: 'tasks',
  metric: 'metrics',
}

function Section({ title, icon: Icon, children, hint }: { title: string; icon: typeof Users; children: React.ReactNode; hint?: string }) {
  return (
    <section>
      <h2 className="flex items-center gap-1.5 text-body font-semibold text-text">
        <Icon className="size-4 text-subtle" aria-hidden /> {title}
      </h2>
      {hint && <p className="mt-0.5 text-caption text-subtle">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

/** Related tab: citations within the library, shared datasets / methods, shared authors. */
export function RelatedWork({ documentId, ready }: { documentId: string; ready: boolean }) {
  const related = useRelatedWork(documentId, ready)
  const [showRef, setShowRef] = useState<string | null>(null)
  if (!ready) return null
  if (related.isPending) return <Skeleton className="h-40 w-full" />
  if (related.isError) return <ErrorState error={related.error} onRetry={() => related.refetch()} />
  const r = related.data
  const citations = [
    ...r.cites.map((c) => ({ ...c, direction: 'cites' as const })),
    ...r.cited_by.map((c) => ({ ...c, direction: 'cited_by' as const })),
  ]
  return (
    <div className="space-y-8">
      <Section
        title="Citations in your library"
        icon={ArrowUpRight}
        hint="References of this paper that match another paper you’ve uploaded (by DOI, arXiv id or title), and papers that cite this one."
      >
        {citations.length === 0 ? (
          <p className="text-small text-muted">None of your other papers cite this one or are cited by it.</p>
        ) : (
          <ul className="space-y-2">
            {citations.map((c) => (
              <li key={`${c.direction}-${c.id}`}>
                <Card className="p-3">
                  <div className="flex items-start gap-3">
                    <Badge tone={c.direction === 'cites' ? 'primary' : 'info'} className="mt-0.5 shrink-0">
                      {c.direction === 'cites' ? (
                        <>
                          <ArrowUpRight className="size-3" aria-hidden /> Cites
                        </>
                      ) : (
                        <>
                          <ArrowDownLeft className="size-3" aria-hidden /> Cited by
                        </>
                      )}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <PaperLine paper={c} />
                      <button
                        type="button"
                        className="mt-1 inline-flex items-center gap-1 text-caption text-subtle hover:text-text"
                        aria-expanded={showRef === `${c.direction}-${c.id}`}
                        onClick={() => setShowRef(showRef === `${c.direction}-${c.id}` ? null : `${c.direction}-${c.id}`)}
                      >
                        Matched by {c.match === 'arxiv' ? 'arXiv id' : c.match === 'doi' ? 'DOI' : 'title'}
                        <ChevronDown className="size-3" aria-hidden />
                      </button>
                      {showRef === `${c.direction}-${c.id}` && (
                        <p className="mt-1 rounded-sm bg-surface-muted p-2 text-caption text-muted">{c.reference}</p>
                      )}
                    </div>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Same datasets and methods"
        icon={Network}
        hint="Papers that use or propose what this paper does; rarer shared items count for more."
      >
        {r.shared_entities.length === 0 ? (
          <p className="text-small text-muted">No other paper shares this paper’s datasets, models or methods yet.</p>
        ) : (
          <ul className="space-y-2">
            {r.shared_entities.map((p) => (
              <li key={p.id}>
                <Card className="p-3">
                  <PaperLine paper={p}>
                    <p className="mt-1.5 text-small text-muted">
                      {(Object.entries(p.shared) as [EntityType, string[]][])
                        .map(([type, names]) => `${SHARED_LABELS[type]}: ${names.join(', ')}`)
                        .join(' · ')}
                    </p>
                  </PaperLine>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {r.same_authors.length > 0 && (
        <Section title="By the same authors" icon={Users}>
          <ul className="space-y-2">
            {r.same_authors.map((p) => (
              <li key={p.id}>
                <Card className="p-3">
                  <PaperLine paper={p}>
                    <p className="mt-1 text-caption text-subtle">Shared: {p.shared_authors.join(', ')}</p>
                  </PaperLine>
                </Card>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}
