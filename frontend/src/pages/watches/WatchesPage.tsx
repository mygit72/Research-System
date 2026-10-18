import { useState } from 'react'
import { MoreVertical, Pause, Play, Plus, Radar, Trash2 } from 'lucide-react'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { Link } from 'react-router-dom'
import { WatchDialog } from '@/components/watches/WatchDialog'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { useDeleteWatch, useRunWatchNow, useUpdateWatch, useWatches } from '@/hooks/useWatches'
import { timeAgo } from '@/lib/format'
import type { Watch } from '@/types/api'

const itemClass =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

function statusTone(watch: Watch): 'success' | 'neutral' {
  return watch.status === 'active' ? 'success' : 'neutral'
}

function WatchCard({ watch, onEdit }: { watch: Watch; onEdit: () => void }) {
  const runNow = useRunWatchNow(watch.id)
  const update = useUpdateWatch(watch.id)
  const remove = useDeleteWatch()
  const inFlight = watch.latest_run?.status === 'queued' || watch.latest_run?.status === 'running'

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/watches/${watch.id}`} className="line-clamp-1 text-small font-semibold text-text hover:text-primary">
            {watch.name}
          </Link>
          <p className="mt-0.5 line-clamp-2 text-caption text-muted">{watch.query}</p>
        </div>
        <Dropdown.Root>
          <Dropdown.Trigger asChild>
            <button className="rounded-md p-1.5 text-muted hover:bg-surface-muted hover:text-text" aria-label="Watch actions">
              <MoreVertical className="size-4" />
            </button>
          </Dropdown.Trigger>
          <Dropdown.Portal>
            <Dropdown.Content
              align="end"
              sideOffset={6}
              className="z-50 w-48 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
            >
              <Dropdown.Item className={itemClass} onSelect={onEdit}>
                Edit
              </Dropdown.Item>
              <Dropdown.Item
                className={itemClass}
                onSelect={() => update.mutate({ status: watch.status === 'active' ? 'paused' : 'active' })}
              >
                {watch.status === 'active' ? (
                  <>
                    <Pause className="size-4 text-muted" /> Pause
                  </>
                ) : (
                  <>
                    <Play className="size-4 text-muted" /> Resume
                  </>
                )}
              </Dropdown.Item>
              <Dropdown.Separator className="my-1 h-px bg-border" />
              <Dropdown.Item
                className={itemClass}
                onSelect={() => {
                  if (confirm(`Delete “${watch.name}”? This also removes its run history and digest.`)) {
                    remove.mutate(watch.id)
                  }
                }}
              >
                <Trash2 className="size-4 text-error" /> Delete
              </Dropdown.Item>
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
      </div>

      <div className="flex items-center gap-2">
        <Badge tone={statusTone(watch)}>{watch.status === 'active' ? 'Active' : 'Paused'}</Badge>
        {watch.status === 'active' && (
          <span className="text-caption text-subtle">next check {timeAgo(watch.next_run_at)}</span>
        )}
      </div>

      {watch.latest_run && (
        <p className="text-caption text-muted">
          Last run: {watch.latest_run.status === 'succeeded' ? (
            <>found {watch.latest_run.candidates_above_threshold} of {watch.latest_run.candidates_found}, added {watch.latest_run.imported_count}</>
          ) : watch.latest_run.status === 'failed' ? (
            <span className="text-error">failed</span>
          ) : (
            'running…'
          )}{' '}
          · {timeAgo(watch.latest_run.created_at)}
        </p>
      )}

      <Button
        variant="secondary"
        size="sm"
        className="self-start"
        loading={runNow.isPending}
        disabled={inFlight}
        onClick={() => runNow.mutate()}
      >
        Run now
      </Button>
    </li>
  )
}

export function WatchesPage() {
  const watches = useWatches()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Watch | null>(null)

  return (
    <PageContainer>
      <PageHeader
        title="Watches"
        description="Save a topic and the system searches arXiv for new matching papers on a schedule — found while you're away."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden /> New watch
          </Button>
        }
      />
      {watches.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : watches.isError ? (
        <ErrorState error={watches.error} onRetry={() => watches.refetch()} />
      ) : watches.data.length === 0 ? (
        <EmptyState
          icon={Radar}
          className="rounded-lg border border-dashed border-border"
          title="No watches yet"
          description="Create one to have the system search arXiv for new papers on a topic, score them, and notify you — no need to come back and ask."
          actions={
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden /> New watch
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {watches.data.map((watch) => (
            <WatchCard key={watch.id} watch={watch} onEdit={() => setEditing(watch)} />
          ))}
        </ul>
      )}
      {creating && <WatchDialog open={creating} onOpenChange={setCreating} />}
      {editing && <WatchDialog open={!!editing} onOpenChange={() => setEditing(null)} watch={editing} />}
    </PageContainer>
  )
}
