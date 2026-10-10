import { useQuery } from '@tanstack/react-query'
import { Activity, BookOpen, MessagesSquare, Upload } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { StatusBadge } from '@/components/documents/StatusBadge'
import { SamplePapersButton } from '@/components/documents/SamplePapersButton'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import { EmptyState, ErrorState, ProgressBar, Skeleton } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'
import { useDocuments, useLibraryStats } from '@/hooks/useDocuments'
import { stageLabel } from '@/lib/documents'
import { timeAgo } from '@/lib/format'
import { primaryNav } from '@/lib/navigation'
import { jobsApi } from '@/services/api'
import { useAuth } from '@/stores/auth'
import { useUploads } from '@/stores/uploads'
import type { DocumentSummary } from '@/types/api'

function greeting() {
  const hour = new Date().getHours()
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
}

function ActiveJobs() {
  const jobs = useQuery({
    queryKey: ['jobs', 'active'],
    queryFn: () => jobsApi.list({ status: ['queued', 'running'], limit: 5 }),
    refetchInterval: (query) => ((query.state.data?.items.length ?? 0) > 0 ? 2000 : 15000),
  })

  if (jobs.isPending) {
    return (
      <div className="space-y-3" aria-label="Loading processing jobs">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-1.5 w-full" />
      </div>
    )
  }
  if (jobs.isError) return <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
  if (jobs.data.items.length === 0) {
    return (
      <p className="text-small text-muted">
        Nothing is processing. Uploaded papers show live progress here.
      </p>
    )
  }
  return (
    <ul className="space-y-4">
      {jobs.data.items.map((job) => (
        <li key={job.id}>
          <div className="mb-1.5 flex items-center justify-between gap-2 text-small">
            <Link
              to={job.subject_id ? `/papers/${job.subject_id}` : '/papers'}
              className="truncate font-medium text-text hover:text-primary"
            >
              {job.stage_detail ?? stageLabel(job.stage)}
            </Link>
            <span className="shrink-0 text-muted tabular-nums">{Math.round(job.progress * 100)}%</span>
          </div>
          <ProgressBar value={job.progress} label="Processing progress" />
        </li>
      ))}
    </ul>
  )
}

function Stat({ label, value, to }: { label: string; value: number | undefined; to: string }) {
  return (
    <Link
      to={to}
      className="rounded-lg border border-border bg-surface px-5 py-4 shadow-sm transition-colors hover:border-border-strong"
    >
      <p className="text-small text-muted">{label}</p>
      <div className="mt-1 text-h1 text-text tabular-nums">
        {value === undefined ? <Skeleton className="h-8 w-12" /> : value}
      </div>
    </Link>
  )
}

function PaperList({ docs, empty }: { docs: DocumentSummary[]; empty: string }) {
  if (!docs.length) return <p className="px-5 py-4 text-small text-muted">{empty}</p>
  return (
    <ul className="divide-y divide-border">
      {docs.map((doc) => (
        <li key={doc.id}>
          <Link
            to={`/papers/${doc.id}`}
            className="flex items-center gap-3 px-5 py-3 hover:bg-surface-muted/50"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-small font-medium text-text">{doc.title}</p>
              <p className="truncate text-caption text-muted">
                {doc.authors_display || doc.original_filename}
                {doc.year ? ` · ${doc.year}` : ''}
              </p>
            </div>
            <StatusBadge doc={doc} />
            <span className="hidden w-20 shrink-0 text-right text-caption text-subtle sm:block">
              {timeAgo(doc.last_opened_at ?? doc.created_at)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

export function HomePage() {
  const user = useAuth((s) => s.user)
  const navigate = useNavigate()
  const openUpload = useUploads((s) => s.setDialogOpen)
  const stats = useLibraryStats()
  const recent = useDocuments({ sort: 'recent', limit: 5 })
  const opened = useDocuments({ sort: 'opened', limit: 5 })
  const firstName = user?.full_name.split(' ')[0]
  const features = primaryNav.filter((item) => item.to !== '/' && item.to !== '/papers')
  const libraryEmpty = stats.data?.total === 0
  const continueReading = (opened.data?.items ?? []).filter((d) => d.last_opened_at)

  return (
    <PageContainer>
      <section className="animate-fade-in">
        <p className="text-small text-muted">
          {greeting()}
          {firstName ? `, ${firstName}` : ''}
        </p>
        <h1 className="mt-1 text-display text-text">Your Research Workspace</h1>
        <p className="mt-2 max-w-2xl text-body text-muted">
          Search, understand, compare, and connect your research papers with AI.
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Button size="lg" onClick={() => openUpload(true)}>
            <Upload className="size-4" aria-hidden /> Upload Papers
          </Button>
          <Button size="lg" variant="secondary" onClick={() => navigate('/chat')}>
            <MessagesSquare className="size-4" aria-hidden /> Start Research Chat
          </Button>
        </div>
      </section>

      <section className="mt-10" aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="sr-only">
          Research overview
        </h2>
        {libraryEmpty ? (
          <Card>
            <EmptyState
              icon={BookOpen}
              title="Your research library is empty."
              description="Upload your first paper to start building your research workspace."
              actions={
                <>
                  <Button onClick={() => openUpload(true)}>Upload Paper</Button>
                  <SamplePapersButton />
                </>
              }
            />
          </Card>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Papers" value={stats.data?.total} to="/papers" />
            <Stat label="Ready to explore" value={stats.data?.ready} to="/papers?status=ready" />
            <Stat label="Processing" value={stats.data?.processing} to="/papers?status=processing" />
            <Stat
              label="Need attention"
              value={stats.data ? stats.data.failed + stats.data.duplicates : undefined}
              to="/papers?status=failed"
            />
          </div>
        )}
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        {!libraryEmpty && (
          <div className="space-y-6 lg:col-span-2">
            <Card>
              <CardHeader className="flex items-center justify-between">
                <div>
                  <CardTitle>Continue reading</CardTitle>
                  <CardDescription>Papers you opened recently.</CardDescription>
                </div>
              </CardHeader>
              <PaperList docs={continueReading} empty="Papers you open will appear here." />
            </Card>
            <Card>
              <CardHeader className="flex items-center justify-between">
                <div>
                  <CardTitle>Recent papers</CardTitle>
                  <CardDescription>Latest additions to your library.</CardDescription>
                </div>
                <Link to="/papers" className="text-small text-primary hover:underline">
                  View all
                </Link>
              </CardHeader>
              {recent.isPending ? (
                <div className="space-y-3 p-5">
                  <Skeleton className="h-5 w-3/4" />
                  <Skeleton className="h-5 w-2/3" />
                </div>
              ) : (
                <PaperList docs={recent.data?.items ?? []} empty="No papers yet." />
              )}
            </Card>
          </div>
        )}
        <Card className={libraryEmpty ? 'lg:col-span-3' : undefined}>
          <CardHeader className="flex items-center gap-2">
            <Activity className="size-4 text-muted" aria-hidden />
            <CardTitle>Processing</CardTitle>
          </CardHeader>
          <CardBody>
            <ActiveJobs />
          </CardBody>
        </Card>
      </div>

      <section className="mt-10" aria-labelledby="features-heading">
        <h2 id="features-heading" className="text-h3 text-text">
          What you can do
        </h2>
        <p className="mt-1 text-small text-muted">Every answer, summary and review cites the passages it comes from.</p>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((item) => (
            <li key={item.to}>
              <Link
                to={item.to}
                className="flex h-full flex-col rounded-lg border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-muted/50"
              >
                <item.icon className="size-4 text-primary" aria-hidden />
                <p className="mt-3 text-small font-medium text-text">{item.label}</p>
                <p className="mt-0.5 text-caption text-muted">{item.description}</p>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </PageContainer>
  )
}
