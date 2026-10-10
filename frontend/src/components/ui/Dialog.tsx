import * as RadixDialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  hideClose,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  children: ReactNode
  className?: string
  hideClose?: boolean
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/40 animate-fade-in" />
        <RadixDialog.Content
          className={cn(
            'fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2',
            'rounded-xl border border-border bg-surface-elevated p-6 shadow-lg animate-fade-in',
            className,
          )}
        >
          <RadixDialog.Title className="text-h3 text-text">{title}</RadixDialog.Title>
          {description ? (
            <RadixDialog.Description className="mt-1 text-small text-muted">
              {description}
            </RadixDialog.Description>
          ) : (
            <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
          )}
          <div className="mt-4">{children}</div>
          {!hideClose && (
            <RadixDialog.Close
              className="absolute top-4 right-4 rounded-md p-1 text-muted hover:bg-surface-muted hover:text-text"
              aria-label="Close"
            >
              <X className="size-4" />
            </RadixDialog.Close>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}
