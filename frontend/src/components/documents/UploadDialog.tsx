import { useRef, useState, type DragEvent } from 'react'
import { CheckCircle2, FileUp, RotateCcw, TriangleAlert, UploadCloud } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ProgressBar } from '@/components/ui/Feedback'
import { cn } from '@/lib/cn'
import { formatBytes } from '@/lib/format'
import { ACCEPTED_EXTENSIONS, ACCEPTED_LABEL, useUploads, type UploadItem } from '@/stores/uploads'

export function UploadZone({ compact = false }: { compact?: boolean }) {
  const add = useUploads((s) => s.add)
  const maxSizeMb = useUploads((s) => s.maxSizeMb)
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const files = Array.from(event.dataTransfer.files)
    if (files.length) add(files)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        'flex flex-col items-center justify-center rounded-lg border-2 border-dashed text-center transition-colors',
        compact ? 'px-4 py-6' : 'px-6 py-10',
        dragging ? 'border-primary bg-primary-soft' : 'border-border-strong bg-surface-muted/50',
      )}
    >
      <UploadCloud className={cn('size-8', dragging ? 'text-primary' : 'text-subtle')} aria-hidden />
      <p className="mt-3 text-body font-medium text-text">Drop research papers here</p>
      <p className="mt-1 text-small text-muted">
        or{' '}
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="font-medium text-primary hover:underline"
        >
          browse files
        </button>
      </p>
      <p className="mt-3 text-caption text-subtle">
        {ACCEPTED_LABEL} · up to {maxSizeMb} MB each · multiple files welcome
      </p>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(',')}
        className="sr-only"
        aria-label="Choose files to upload"
        onChange={(e) => {
          if (e.target.files?.length) add(Array.from(e.target.files))
          e.target.value = ''
        }}
      />
    </div>
  )
}

function UploadRow({ item }: { item: UploadItem }) {
  const retry = useUploads((s) => s.retry)
  const setOpen = useUploads((s) => s.setDialogOpen)
  return (
    <li className="flex items-start gap-3 py-3">
      <div className="mt-0.5 shrink-0">
        {item.state === 'uploaded' ? (
          <CheckCircle2 className="size-4 text-success" aria-label="Uploaded" />
        ) : item.state === 'error' ? (
          <TriangleAlert className="size-4 text-error" aria-label="Failed" />
        ) : (
          <FileUp className="size-4 text-subtle" aria-hidden />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <p className="truncate text-small font-medium text-text">{item.file.name}</p>
          <span className="shrink-0 text-caption text-subtle">{formatBytes(item.file.size)}</span>
        </div>
        {item.state === 'uploading' || item.state === 'pending' ? (
          <div className="mt-1.5 flex items-center gap-2">
            <ProgressBar value={item.progress} label={`Uploading ${item.file.name}`} />
            <span className="w-16 shrink-0 text-right text-caption text-muted">
              {item.state === 'pending' ? 'Waiting' : `${Math.round(item.progress * 100)}%`}
            </span>
          </div>
        ) : item.state === 'uploaded' ? (
          <p className="text-caption text-muted">
            Uploaded — processing has started.{' '}
            {item.duplicate && <span className="text-warning">Looks like a duplicate. </span>}
            <Link
              to={`/papers/${item.documentId}`}
              onClick={() => setOpen(false)}
              className="text-primary hover:underline"
            >
              Open
            </Link>
          </p>
        ) : (
          <div className="flex items-start justify-between gap-2">
            <p className="text-caption text-error">
              {item.error}
              {item.hint && <span className="text-muted"> {item.hint}</span>}
            </p>
            <button
              onClick={() => retry(item.id)}
              className="flex shrink-0 items-center gap-1 text-caption text-primary hover:underline"
            >
              <RotateCcw className="size-3" /> Retry
            </button>
          </div>
        )}
      </div>
    </li>
  )
}

export function UploadDialog() {
  const open = useUploads((s) => s.dialogOpen)
  const setOpen = useUploads((s) => s.setDialogOpen)
  const items = useUploads((s) => s.items)
  const clearFinished = useUploads((s) => s.clearFinished)
  const busy = items.some((i) => i.state === 'pending' || i.state === 'uploading')
  const done = items.filter((i) => i.state === 'uploaded').length

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title="Upload papers"
      description="We'll read each paper, extract its structure and metadata, and index it."
      className="max-w-xl"
    >
      <UploadZone compact={items.length > 0} />
      {items.length > 0 && (
        <>
          <ul className="mt-4 max-h-72 divide-y divide-border overflow-y-auto" aria-live="polite">
            {items.map((item) => (
              <UploadRow key={item.id} item={item} />
            ))}
          </ul>
          <div className="mt-4 flex items-center justify-between gap-2">
            <p className="text-caption text-muted">
              {busy ? 'Uploading… you can close this window.' : `${done} uploaded`}
            </p>
            <div className="flex gap-2">
              {!busy && (
                <Button variant="ghost" size="sm" onClick={clearFinished}>
                  Clear list
                </Button>
              )}
              <Button size="sm" onClick={() => setOpen(false)}>
                {busy ? 'Continue in background' : 'Done'}
              </Button>
            </div>
          </div>
        </>
      )}
    </Dialog>
  )
}
