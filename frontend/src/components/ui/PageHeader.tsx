import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function PageContainer({
  children,
  className,
  width = 'default',
}: {
  children: ReactNode
  className?: string
  width?: 'default' | 'narrow' | 'wide'
}) {
  const max = { narrow: 'max-w-3xl', default: 'max-w-5xl', wide: 'max-w-7xl' }[width]
  return (
    <div className={cn('mx-auto w-full px-4 py-8 sm:px-6 lg:px-8', max, className)}>
      {children}
    </div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-h1 text-text">{title}</h1>
        {description && <p className="mt-1 text-body text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  )
}
