import { useState } from 'react'
import { Check, Copy, ExternalLink, FileText, Pencil, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { WatchDialog } from '@/components/watches/WatchDialog'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { useCollections } from '@/hooks/useOrganization'
import { useProjects } from '@/hooks/useProjects'
import {
  useDeleteWatch,
  useImportDigestEntry,
  useRunWatchNow,
  useWatch,
  useWatchDigest,
  useWatchRuns,
} from '@/hooks/useWatches'
import { timeAgo } from '@/lib/format'
import type { DigestEntry, WatchRun } from '@/types/api'

function RunRow({ run }: { run: WatchRun }) {
  const tone = run.status === 'succeeded' ? 'success' : run.status === 'failed' ? 'error' : 'neutral'
  return (
    <li className="flex items-center justify-between gap-3 border-b border-border py-2 text-small last:border-0">
      <div className="flex items-center gap-2">
        <Badge tone={tone}>{run.status}</Badge>
        <span className="text-caption text-subtle">{run.trigger === 'manual' ? 'Run now' : 'Scheduled'}</span>
      </div>
      <span className="text-caption text-subtle">
        {run.status === 'succeeded' && `${run.candidates_above_threshold} of ${run.candidates_found} kept, ${run.imported_count} added · `}
        {timeAgo(run.created_at)}
      </span>
    </li>
  )
}

function DigestRow({ entry, watchId }: { entry: DigestEntry; watchId: string }) {
  const importEntry = useImportDigestEntry(watchId)
  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <a
            href={`https://arxiv.org/abs/${entry.arxiv_id}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-small font-medium text-text hover:text-primary"
          >
            {entry.title} <ExternalLink className="size-3" aria-hidden />
          </a>
          {entry.authors.length > 0 && (
            <p className="mt-0.5 text-caption text-subtle">{entry.authors.map((a) => a.name).join(', ')}</p>
          )}
          {entry.blurb && <p className="mt-1.5 text-small text-muted">{entry.blurb}</p>}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className="text-caption text-subtle">{Math.round(entry.score * 100)}% match</span>
          {entry.import_status === 'pending' ? (
            <Button size="sm" variant="secondary" loading={importEntry.isPending} onClick={() => importEntry.mutate(entry.id)}>
              Add to library
            </Button>
          ) : entry.document_id ? (
            <Link to={`/papers/${entry.document_id}`} className="text-caption font-medium text-primary hover:underline">
              {entry.import_status === 'imported' ? 'Added' : 'Already in library'}
            </Link>
          ) : (
            <span className="text-caption text-subtle">Already in library</span>
          )}
        </div>
      </div>
      <details className="mt-2 text-caption text-subtle">
        <summary className="cursor-pointer">Why this matched</summary>
        <dl className="mt-2 grid gap-1 sm:grid-cols-[140px_1fr]">
          <dt>Search terms</dt>
          <dd>{entry.trace.search_query}</dd>
          <dt>Compared against</dt>
          <dd>
            {entry.trace.anchor_topic}
            {entry.trace.anchor_project_question && ` + “${entry.trace.anchor_project_question}”`}
          </dd>
          <dt>Rank</dt>
          <dd>
            {entry.trace.rank} of {entry.trace.candidates_in_run} candidates found
          </dd>
          <dt>Score vs. threshold</dt>
          <dd>
            {Math.round(entry.score * 100)}% vs. a {Math.round(entry.trace.relevance_threshold * 100)}% threshold
          </dd>
        </dl>
      </details>
    </li>
  )
}

function PublicLinkBox({ watchId }: { watchId: string }) {
  const [copied, setCopied] = useState(false)
  const url = `${window.location.origin}/w/${watchId}`
  const copy = () => {
    void navigator.clipboard?.writeText(url).then(() => {
      setCopied(true)
      toast.success('Link copied')
      window.setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <div className="mb-6 flex items-center gap-2 rounded-lg border border-border bg-surface p-3">
      <span className="min-w-0 flex-1 truncate text-small text-text">{url}</span>
      <Button size="sm" variant="secondary" onClick={copy}>
        {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />} Copy link
      </Button>
    </div>
  )
}

export function WatchPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const watch = useWatch(id)
  const runs = useWatchRuns(id)
  const digest = useWatchDigest(id)
  const collections = useCollections()
  const projects = useProjects()
  const runNow = useRunWatchNow(id)
  const remove = useDeleteWatch()
  const [editing, setEditing] = useState(false)

  if (watch.isPending) {
    return (
      <PageContainer>
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="mt-6 h-48 w-full" />
      </PageContainer>
    )
  }
  if (watch.isError) {
    return (
      <PageContainer>
        <ErrorState error={watch.error} onRetry={() => watch.refetch()} />
      </PageContainer>
    )
  }
  const w = watch.data
  const collection = collections.data?.find((c) => c.id === w.collection_id)
  const project = projects.data?.find((p) => p.id === w.project_id)
  const inFlight = w.latest_run?.status === 'queued' || w.latest_run?.status === 'running'

  return (
    <PageContainer>
      <PageHeader
        title={w.name}
        description={w.query}
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" loading={runNow.isPending} disabled={inFlight} onClick={() => runNow.mutate()}>
              Run now
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)} aria-label="Edit watch">
              <Pencil className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Delete watch"
              onClick={() => {
                if (confirm(`Delete “${w.name}”? This also removes its run history and digest.`)) {
                  remove.mutate(w.id, { onSuccess: () => navigate('/watches') })
                }
              }}
            >
              <Trash2 className="size-4 text-error" />
            </Button>
          </div>
        }
      />

      <dl className="mb-8 grid gap-4 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-caption text-subtle">Status</dt>
          <dd className="mt-0.5"><Badge tone={w.status === 'active' ? 'success' : 'neutral'}>{w.status}</Badge></dd>
        </div>
        <div>
          <dt className="text-caption text-subtle">Checks every</dt>
          <dd className="mt-0.5 text-small text-text">{w.interval_hours} hours</dd>
        </div>
        <div>
          <dt className="text-caption text-subtle">Adds matches to</dt>
          <dd className="mt-0.5 text-small text-text">
            {collection ? <Link to={`/collections/${collection.id}`} className="text-primary hover:underline">{collection.name}</Link> : 'No collection'}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-subtle">Linked project</dt>
          <dd className="mt-0.5 text-small text-text">
            {project ? <Link to={`/projects/${project.id}`} className="text-primary hover:underline">{project.title}</Link> : 'None'}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-subtle">Relevance threshold</dt>
          <dd className="mt-0.5 text-small text-text">{Math.round(w.relevance_threshold * 100)}%</dd>
        </div>
        <div>
          <dt className="text-caption text-subtle">Auto-import</dt>
          <dd className="mt-0.5 text-small text-text">{w.auto_import ? 'On' : 'Off (review queue)'}</dd>
        </div>
        <div>
          <dt className="text-caption text-subtle">Next check</dt>
          <dd className="mt-0.5 text-small text-text">{w.status === 'active' ? timeAgo(w.next_run_at) : '—'}</dd>
        </div>
        <div>
          <dt className="text-caption text-subtle">Last searched</dt>
          <dd className="mt-0.5 text-small text-text">{w.last_searched_at ? timeAgo(w.last_searched_at) : 'Never'}</dd>
        </div>
      </dl>

      {w.is_public && <PublicLinkBox watchId={w.id} />}

      {w.latest_run?.report_id && (
        <Link
          to={`/reviews/${w.latest_run.report_id}`}
          className="mb-6 flex items-center gap-2 rounded-lg border border-border bg-surface p-3 text-small font-medium text-primary hover:underline"
        >
          <FileText className="size-4" aria-hidden /> View the literature review from the latest run
        </Link>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <section>
          <h2 className="mb-3 text-h3 text-text">Digest</h2>
          {digest.isPending ? (
            <Skeleton className="h-32" />
          ) : digest.data && digest.data.items.length > 0 ? (
            <ul className="space-y-3">
              {digest.data.items.map((entry) => (
                <DigestRow key={entry.id} entry={entry} watchId={id} />
              ))}
            </ul>
          ) : (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-small text-muted">
              Nothing yet — run now, or wait for the next scheduled check.
            </p>
          )}
        </section>
        <section>
          <h2 className="mb-3 text-h3 text-text">Run history</h2>
          {runs.isPending ? (
            <Skeleton className="h-32" />
          ) : runs.data && runs.data.items.length > 0 ? (
            <ul>
              {runs.data.items.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </ul>
          ) : (
            <p className="text-small text-muted">No runs yet.</p>
          )}
        </section>
      </div>
      {editing && <WatchDialog open={editing} onOpenChange={setEditing} watch={w} />}
    </PageContainer>
  )
}
