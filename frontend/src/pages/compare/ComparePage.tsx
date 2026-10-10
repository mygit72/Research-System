import { useMemo } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { GitCompareArrows, Info, Plus, Search, Trash2, X } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { PaperPicker } from '@/components/documents/PaperPicker'
import { Card, CardBody, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { KIND_LABELS, MAX_COMPARE, MIN_COMPARE, STATUS_LABEL, compareReason } from '@/lib/compare'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { queryClient } from '@/lib/queryClient'
import { comparisonsApi, documentsApi, systemApi } from '@/services/api'
import type { ComparisonKind } from '@/types/api'

const KINDS: { value: ComparisonKind; description: string }[] = [
  { value: 'papers', description: 'Problem, data, model, training, evaluation, metrics, results, limitations, compute' },
  {
    value: 'methodology',
    description: 'Architecture, training data, preprocessing, objective, loss, optimization, hyperparameters, evaluation',
  },
]


function NewComparison() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const ids = useMemo(() => (params.get('papers') ?? '').split(',').filter(Boolean).slice(0, MAX_COMPARE), [params])
  const kind = (params.get('kind') as ComparisonKind) === 'methodology' ? 'methodology' : 'papers'
  const papers = useQuery({
    queryKey: ['documents', 'detail-many', ids],
    queryFn: () => Promise.all(ids.map((id) => documentsApi.get(id))),
    enabled: ids.length > 0,
  })
  const ai = useQuery({ queryKey: ['ai-status'], queryFn: systemApi.aiStatus, staleTime: 30_000 })
  const update = (next: { ids?: string[]; kind?: ComparisonKind }) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        const nextIds = next.ids ?? ids
        if (nextIds.length) p.set('papers', nextIds.join(','))
        else p.delete('papers')
        if ((next.kind ?? kind) === 'methodology') p.set('kind', 'methodology')
        else p.delete('kind')
        return p
      },
      { replace: true },
    )
  const create = useMutation({
    mutationFn: () => comparisonsApi.create({ document_ids: ids, kind }),
    onSuccess: (comparison) => {
      void queryClient.invalidateQueries({ queryKey: ['comparisons'] })
      queryClient.setQueryData(['comparisons', comparison.id], comparison)
      navigate(`/compare/${comparison.id}`)
    },
    onError: (e) => toast.error(e.message),
  })
  const docs = papers.data ?? []
  const blocked = docs.map((d) => compareReason(d) && `${d.title}: ${compareReason(d)}`).find(Boolean)
  const llm = ai.data?.llm
  const problem =
    ids.length < MIN_COMPARE
      ? `Add ${MIN_COMPARE - ids.length} more paper${MIN_COMPARE - ids.length === 1 ? '' : 's'} to compare.`
      : blocked || (llm && !llm.ready ? `The language model isn’t ready. ${llm.problem ?? ''}` : null)

  return (
    <Card>
      <CardHeader>
        <CardTitle>New comparison</CardTitle>
        <CardDescription>
          Pick {MIN_COMPARE} to {MAX_COMPARE} papers. Every cell is written from the paper’s own passages, cites them,
          and says “Not reported” when the paper doesn’t.
        </CardDescription>
      </CardHeader>
      <CardBody className="space-y-5">
        <div>
          <p className="mb-2 text-small font-medium text-text">
            Papers <span className="font-normal text-muted">({ids.length} of {MAX_COMPARE})</span>
          </p>
          {papers.isError ? (
            <ErrorState error={papers.error} title="We couldn't load these papers" onRetry={() => papers.refetch()} />
          ) : (
            <ol className="mb-3 space-y-2">
              {ids.map((id, index) => {
                const doc = docs.find((d) => d.id === id)
                return (
                  <li key={id} className="flex items-center gap-3 rounded-md border border-border px-3 py-2">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary-soft text-caption font-semibold text-primary">
                      {String.fromCharCode(65 + index)}
                    </span>
                    <span className="min-w-0 flex-1">
                      {doc ? (
                        <>
                          <span className="line-clamp-1 text-small font-medium text-text">{doc.title}</span>
                          <span className="text-caption text-muted">
                            {compareReason(doc) ?? ([doc.authors_display, doc.year].filter(Boolean).join(' · ') || ' ')}
                          </span>
                        </>
                      ) : (
                        <Skeleton className="h-4 w-2/3" />
                      )}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove ${doc?.title ?? 'paper'}`}
                      onClick={() => update({ ids: ids.filter((other) => other !== id) })}
                    >
                      <X className="size-4" />
                    </Button>
                  </li>
                )
              })}
            </ol>
          )}
          {ids.length < MAX_COMPARE && <PaperPicker picked={ids} reason={compareReason} disabled={ids.length >= MAX_COMPARE} onAdd={(doc) => update({ ids: [...ids, doc.id] })} />}
        </div>

        <fieldset>
          <legend className="mb-2 text-small font-medium text-text">Compare</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {KINDS.map(({ value, description }) => (
              <button
                key={value}
                type="button"
                aria-pressed={kind === value}
                onClick={() => update({ kind: value })}
                className={cn(
                  'rounded-md border p-3 text-left transition-colors',
                  kind === value ? 'border-primary bg-primary-soft/40' : 'border-border hover:border-border-strong',
                )}
              >
                <span className="block text-small font-semibold text-text">{KIND_LABELS[value]}</span>
                <span className="mt-0.5 block text-caption text-muted">{description}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!!problem || (papers.isPending && ids.length > 0)}>
            {!create.isPending && <GitCompareArrows className="size-4" aria-hidden />} Compare
          </Button>
          {problem && (
            <p className="flex items-center gap-1.5 text-small text-muted">
              <Info className="size-4 shrink-0" aria-hidden /> {problem}
            </p>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

function RecentComparisons() {
  const list = useQuery({ queryKey: ['comparisons', 'list'], queryFn: () => comparisonsApi.list({ limit: 30 }) })
  const remove = useMutation({
    mutationFn: comparisonsApi.remove,
    onSuccess: () => {
      toast.success('Comparison deleted')
      void queryClient.invalidateQueries({ queryKey: ['comparisons'] })
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <section aria-labelledby="recent-comparisons">
      <h2 id="recent-comparisons" className="mb-3 text-h3 text-text">
        Recent comparisons
      </h2>
      {list.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : list.data.length === 0 ? (
        <EmptyState
          icon={Search}
          className="rounded-lg border border-dashed border-border py-10"
          title="No comparisons yet"
          description="Select papers in your library and choose “Compare selected”, or add them above."
          actions={
            <Link to="/papers">
              <Button variant="secondary">
                <Plus className="size-4" aria-hidden /> Pick papers in the library
              </Button>
            </Link>
          }
        />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {list.data.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-4 py-3">
              <Link to={`/compare/${c.id}`} className="min-w-0 flex-1 group">
                <span className="line-clamp-1 text-small font-medium text-text group-hover:text-primary">{c.title}</span>
                <span className="text-caption text-muted">
                  {c.columns.length} papers · {KIND_LABELS[c.kind]} · {timeAgo(c.created_at)}
                </span>
              </Link>
              <Badge tone={STATUS_LABEL[c.status].tone}>{STATUS_LABEL[c.status].label}</Badge>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Delete comparison ${c.title}`}
                onClick={() => remove.mutate(c.id)}
              >
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function ComparePage() {
  return (
    <PageContainer>
      <PageHeader title="Compare" description="Put papers side by side: what each one does, how, and how well." />
      <div className="space-y-10">
        <NewComparison />
        <RecentComparisons />
      </div>
    </PageContainer>
  )
}
