import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Radar } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { LogoMark } from '@/components/ui/Logo'
import { publicApi } from '@/services/api'
import type { PublicDigestEntry } from '@/types/api'

function DigestRow({ entry }: { entry: PublicDigestEntry }) {
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
            <p className="mt-0.5 text-caption text-subtle">
              {entry.authors.map((a) => a.name).join(', ')}
            </p>
          )}
          {entry.blurb && <p className="mt-1.5 text-small text-muted">{entry.blurb}</p>}
        </div>
        <span className="shrink-0 text-caption text-subtle">{Math.round(entry.score * 100)}% match</span>
      </div>
    </li>
  )
}

/** A watch's owner has made this public: no login, a minimal standalone page (no AppShell). */
export function PublicWatchPage() {
  const { id = '' } = useParams()
  const watch = useQuery({ queryKey: ['public', 'watch', id], queryFn: () => publicApi.getWatch(id) })
  const digest = useQuery({
    queryKey: ['public', 'watch', id, 'digest'],
    queryFn: () => publicApi.getDigest(id),
    enabled: watch.isSuccess,
  })

  return (
    <div className="min-h-dvh bg-bg">
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <LogoMark className="size-6" />
        <span className="text-small font-medium text-text">Research Intelligence</span>
      </header>
      <main className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
        {watch.isPending ? (
          <>
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="mt-6 h-48 w-full" />
          </>
        ) : watch.isError ? (
          <ErrorState title="This watch isn't available" error={watch.error} />
        ) : (
          <>
            <div className="mb-1 flex items-center gap-2">
              <Radar className="size-5 text-primary" aria-hidden />
              <h1 className="text-h1 text-text">{watch.data.name}</h1>
            </div>
            <p className="text-body text-muted">{watch.data.query}</p>
            <Badge tone={watch.data.status === 'active' ? 'success' : 'neutral'} className="mt-2">
              {watch.data.status}
            </Badge>

            <h2 className="mt-8 mb-3 text-h3 text-text">Recent matches</h2>
            {digest.isPending ? (
              <Skeleton className="h-32" />
            ) : digest.data && digest.data.items.length > 0 ? (
              <ul className="space-y-3">
                {digest.data.items.map((entry) => (
                  <DigestRow key={entry.id} entry={entry} />
                ))}
              </ul>
            ) : (
              <p className="rounded-lg border border-dashed border-border p-6 text-center text-small text-muted">
                Nothing yet.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  )
}
