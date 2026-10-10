import * as RadixTabs from '@radix-ui/react-tabs'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export const Tabs = RadixTabs.Root
export const TabsContent = RadixTabs.Content

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <RadixTabs.List
      className={cn('flex gap-1 overflow-x-auto border-b border-border', className)}
    >
      {children}
    </RadixTabs.List>
  )
}

export function TabsTrigger({
  value,
  children,
  count,
  disabled,
}: {
  value: string
  children: ReactNode
  count?: number
  disabled?: boolean
}) {
  return (
    <RadixTabs.Trigger
      value={value}
      disabled={disabled}
      className={cn(
        '-mb-px flex h-10 items-center gap-1.5 border-b-2 border-transparent px-3 text-small whitespace-nowrap text-muted transition-colors',
        'hover:text-text disabled:cursor-not-allowed disabled:opacity-40',
        'data-[state=active]:border-primary data-[state=active]:font-medium data-[state=active]:text-text',
      )}
    >
      {children}
      {count !== undefined && (
        <span className="rounded-sm bg-surface-muted px-1.5 text-caption text-subtle tabular-nums">
          {count}
        </span>
      )}
    </RadixTabs.Trigger>
  )
}
