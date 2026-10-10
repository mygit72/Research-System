/** Skeleton, ProgressBar, EmptyState, ErrorState, Kbd, Spinner. */
import type { HTMLAttributes, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/cn'
import { ApiError } from '@/services/http'
import { Button } from './Button'

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn('animate-pulse rounded-md bg-surface-muted', className)}
      {...props}
    />
  )
}

export function ProgressBar({
  value,
  label,
  className,
}: {
  value: number
  label: string
  className?: string
}) {
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-surface-muted', className)}
    >
      <div
        className="h-full rounded-full bg-primary transition-[width] duration-300"
        style={{ width: `${percent}%` }}
      />
    </div>
  )
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  actions,
  className,
}: {
  icon: LucideIcon
  title: string
  description: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center px-6 py-14 text-center animate-fade-in',
        className,
      )}
    >
      <div className="mb-4 flex size-11 items-center justify-center rounded-lg border border-border bg-surface-muted">
        <Icon className="size-5 text-muted" aria-hidden />
      </div>
      <h2 className="text-h3 text-text">{title}</h2>
      <p className="mt-1.5 max-w-md text-body text-muted">{description}</p>
      {actions && <div className="mt-5 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  )
}

/** What happened, why it might have happened, what the user can do. */
export function ErrorState({
  error,
  title = "We couldn't load this",
  onRetry,
  className,
}: {
  error: unknown
  title?: string
  onRetry?: () => void
  className?: string
}) {
  const apiError = error instanceof ApiError ? error : null
  const plainMessage =
    !apiError && error && typeof error === 'object' && 'message' in error && typeof error.message === 'string'
      ? error.message
      : null
  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-3 rounded-lg border border-error/30 bg-error-soft p-4',
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-5 shrink-0 text-error" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-text">{title}</p>
        <p className="mt-0.5 text-small text-muted">
          {apiError?.message ?? plainMessage ?? 'An unexpected error occurred.'}
          {apiError?.hint && <> {apiError.hint}</>}
        </p>
        {apiError?.requestId && (
          <p className="mt-1 text-caption text-subtle">
            Reference: <code>{apiError.requestId}</code>
          </p>
        )}
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        'inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-border',
        'bg-surface-muted px-1 font-mono text-[0.6875rem] text-muted',
        className,
      )}
    >
      {children}
    </kbd>
  )
}
