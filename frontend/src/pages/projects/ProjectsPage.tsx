import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Lightbulb } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { useCollections } from '@/hooks/useOrganization'
import { useProjects } from '@/hooks/useProjects'
import { timeAgo } from '@/lib/format'
import { collectionsApi, projectsApi } from '@/services/api'
import { toast } from 'sonner'

const STEPS = ['Question', 'Background', 'Gap & hypothesis', 'Methods', 'Experiments', 'Outline']

function NewProject() {
  const [searchParams] = useSearchParams()
  const sourcePaperId = searchParams.get('paper_id') ?? ''
  const sourcePaperTitle = searchParams.get('paper_title') ?? 'Selected paper'
  const [idea, setIdea] = useState(() => searchParams.get('idea') ?? '')
  const [collectionId, setCollectionId] = useState('')
  const [saving, setSaving] = useState(false)
  const collections = useCollections()
  const navigate = useNavigate()
  const tooShort = idea.trim().split(/\s+/).filter(Boolean).length < 3

  const create = async () => {
    setSaving(true)
    let sourceCollectionId: string | null = null
    try {
      if (sourcePaperId) {
        const collection = await collectionsApi.create({
          name: `Research: ${sourcePaperTitle}`.slice(0, 120),
          description: `Research project grounded in ${sourcePaperTitle}. Add related papers to this collection as the project develops.`,
          kind: 'project',
          document_ids: [sourcePaperId],
        })
        sourceCollectionId = collection.id
      }
      const project = await projectsApi.create({
        idea: idea.trim(),
        collection_id: sourceCollectionId ?? (collectionId || null),
      })
      navigate(`/projects/${project.id}`)
    } catch (error) {
      if (sourceCollectionId) await collectionsApi.remove(sourceCollectionId).catch(() => {})
      toast.error((error as Error).message)
      setSaving(false)
    }
  }

  return (
    <section className="rounded-lg border border-border bg-surface p-5 shadow-sm">
      <label className="block">
        <span className="text-small font-medium text-text">Your idea</span>
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={3}
          placeholder="e.g. Adapt retrieval-augmented generators to the retriever they're paired with, using low-rank adapters, and see whether answers get more accurate."
          className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-small text-text placeholder:text-subtle focus:border-primary focus:outline-none"
        />
      </label>
      {sourcePaperId ? (
        <p className="mt-3 max-w-2xl text-small text-muted">
          Starting paper: <span className="font-medium text-text">{sourcePaperTitle}</span>. It will be attached to a
          project collection; you can add related papers as you develop the question.
        </p>
      ) : (
        <label className="mt-3 block max-w-sm">
          <span className="text-small font-medium text-text">Papers to build on</span>
          <select
            value={collectionId}
            onChange={(e) => setCollectionId(e.target.value)}
            className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text"
          >
            <option value="">Find them from the idea</option>
            {collections.data?.map((c) => (
              <option key={c.id} value={c.id}>
                Collection: {c.name} ({c.paper_count})
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button onClick={create} disabled={tooShort} loading={saving}>
          <Lightbulb className="size-4" aria-hidden /> Start project
        </Button>
        <span className="text-caption text-subtle">
          You’ll go through {STEPS.join(' → ')}. Every suggestion shows the papers it comes from; you decide what to keep.
        </span>
      </div>
    </section>
  )
}

export function ProjectsPage() {
  const projects = useProjects()
  return (
    <PageContainer>
      <PageHeader
        title="Research Projects"
        description="Turn an idea into a research plan: questions, background, a gap and hypothesis, methods, experiments and a paper outline — grounded in your papers."
      />
      <NewProject />
      <h2 className="mt-10 mb-3 text-h3 text-text">Your projects</h2>
      {projects.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : projects.isError ? (
        <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
      ) : projects.data.length === 0 ? (
        <EmptyState
          icon={Lightbulb}
          className="rounded-lg border border-dashed border-border"
          title="No projects yet"
          description="Describe an idea above to start one."
        />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {projects.data.map((p) => (
            <li key={p.id}>
              <Link to={`/projects/${p.id}`} className="block px-4 py-3 hover:bg-surface-muted">
                <p className="font-medium text-text">{p.title}</p>
                <p className="line-clamp-1 text-small text-muted">{p.question || p.idea}</p>
                <p className="text-caption text-subtle">Updated {timeAgo(p.updated_at)}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PageContainer>
  )
}
