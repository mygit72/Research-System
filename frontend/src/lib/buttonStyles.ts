/** Button classes, shared by <Button> and links styled as buttons. */
import { cn } from '@/lib/cn'

export const variants = {
  primary: 'bg-primary text-primary-fg hover:bg-primary-hover shadow-sm',
  secondary: 'bg-surface text-text border border-border hover:bg-surface-muted shadow-sm',
  ghost: 'text-muted hover:text-text hover:bg-surface-muted',
  danger: 'bg-error text-on-error hover:opacity-90 shadow-sm',
  link: 'text-primary hover:underline underline-offset-4 px-0 h-auto',
} as const

export const sizes = {
  sm: 'h-8 px-3 text-small gap-1.5',
  md: 'h-9 px-3.5 text-small gap-2',
  lg: 'h-11 px-5 text-body gap-2',
  icon: 'h-9 w-9 justify-center',
  'icon-sm': 'h-8 w-8 justify-center',
} as const

/** Button styling for elements that aren't buttons (router links that look like buttons). */
export function buttonClass(variant: keyof typeof variants = 'primary', size: keyof typeof sizes = 'md', className?: string) {
  return cn(
    'inline-flex shrink-0 items-center rounded-md font-medium whitespace-nowrap',
    'transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50',
    variants[variant],
    sizes[size],
    className,
  )
}
