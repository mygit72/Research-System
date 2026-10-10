import * as Popover from '@radix-ui/react-popover'
import { useMutation } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ProgressBar } from '@/components/ui/Feedback'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/cn'
import { estimateRemaining, formatDuration } from '@/lib/format'
import { queryClient } from '@/lib/queryClient'
import { documentsApi } from '@/services/api'
import { stageLabel } from '@/lib/documents'
import type { DocumentSummary } from '@/types/api'

function Dot({ className }: { className: string }) {
  return <span className={cn('size-1.5 rounded-full', className)} aria-hidden />
}

export function StatusBadge({ doc, className }: { doc: DocumentSummary; className?: string }) {
  const retry = useMutation({
    mutationFn: () => documentsApi.reprocess(doc.id),
    onSuccess: () => {
      toast.success('Processing restarted')
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
    onError: (error) => toast.error(error.message),
  })

  if (doc.status === 'ready' && doc.index_status === 'failed') {
    return (
      <Tooltip content={doc.index_error ?? 'Search indexing failed'}>
        <span className={className}>
          <Badge tone="warning">
            <Dot className="bg-warning" /> Not searchable
          </Badge>
        </span>
      </Tooltip>
    )
  }

  if (doc.status === 'ready') {
    return (
      <Badge tone="success" className={className}>
        <Dot className="bg-success" /> Ready
      </Badge>
    )
  }

  const processing = doc.processing
  const inProgress = doc.status === 'queued' || doc.status === 'processing'
  const eta = processing ? estimateRemaining(processing.started_at, processing.progress) : null

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          className={cn('rounded-sm', className)}
          aria-label={inProgress ? 'Processing details' : 'Error details'}
          onClick={(e) => e.stopPropagation()}
        >
          {inProgress ? (
            <Badge tone="warning">
              <Loader2 className="size-3 animate-spin" aria-hidden />
              {processing ? `${Math.round(processing.progress * 100)}%` : 'Queued'}
            </Badge>
          ) : (
            <Badge tone="error">
              <Dot className="bg-error" /> Failed
            </Badge>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          align="start"
          onClick={(e) => e.stopPropagation()}
          className="z-50 w-72 rounded-lg border border-border bg-surface-elevated p-4 shadow-lg animate-fade-in"
        >
          {inProgress ? (
            <div aria-live="polite">
              <p className="text-small font-medium text-text">Processing paper…</p>
              <p className="mt-1 text-caption text-muted">
                {processing?.stage_detail ?? stageLabel(processing?.stage)}
              </p>
              <ProgressBar
                className="mt-3"
                value={processing?.progress ?? 0}
                label="Processing progress"
              />
              <p className="mt-2 text-caption text-subtle">
                {eta ? `About ${formatDuration(eta)} remaining` : 'Estimating time remaining…'}
              </p>
            </div>
          ) : (
            <div>
              <p className="text-small font-medium text-text">We couldn't process this document.</p>
              <p className="mt-1 text-caption text-muted">
                {doc.error_message ?? 'The file may be corrupted or in an unusual format.'}
              </p>
              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={() => retry.mutate()} loading={retry.isPending}>
                  Retry
                </Button>
              </div>
            </div>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

export function DuplicateBadge({ doc }: { doc: DocumentSummary }) {
  if (!doc.duplicate_kind) return null
  const label = {
    exact_duplicate: 'Duplicate',
    probable_duplicate: 'Probable duplicate',
    possible_duplicate: 'Possible duplicate',
  }[doc.duplicate_kind]
  return <Badge tone="info">{label}</Badge>
}
