import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const tones = {
  neutral: 'bg-surface-muted text-muted border-border',
  primary: 'bg-primary-soft text-primary border-transparent',
  success: 'bg-success-soft text-success border-transparent',
  warning: 'bg-warning-soft text-warning border-transparent',
  error: 'bg-error-soft text-error border-transparent',
  info: 'bg-info-soft text-info border-transparent',
} as const

export type BadgeTone = keyof typeof tones

export function Badge({
  tone = 'neutral',
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-caption font-medium',
        tones[tone],
        className,
      )}
      {...props}
    />
  )
}
