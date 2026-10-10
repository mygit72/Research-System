import * as RadixDialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** Slide-over panel (mobile filters, side panels). Focus-trapped, Esc to close. */
export function Sheet({
  open,
  onOpenChange,
  title,
  children,
  footer,
  side = 'right',
  className,
  bare,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode
  footer?: ReactNode
  side?: 'left' | 'right'
  className?: string
  /** The content brings its own header and scrolling (the title stays for screen readers). */
  bare?: boolean
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/40 animate-fade-in" />
        <RadixDialog.Content
          className={cn(
            'fixed inset-y-0 z-50 flex w-[min(22rem,calc(100vw-2rem))] flex-col bg-surface-elevated shadow-lg animate-fade-in',
            side === 'right' ? 'right-0 border-l border-border' : 'left-0 border-r border-border',
            className,
          )}
        >
          {bare ? (
            <>
              <RadixDialog.Title className="sr-only">{title}</RadixDialog.Title>
              <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
              <div className="min-h-0 flex-1">{children}</div>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <RadixDialog.Title className="text-h3 text-text">{title}</RadixDialog.Title>
                <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
                <RadixDialog.Close
                  className="rounded-md p-1 text-muted hover:bg-surface-muted hover:text-text"
                  aria-label="Close"
                >
                  <X className="size-4" />
                </RadixDialog.Close>
              </div>
              <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>
              {footer && <div className="border-t border-border px-5 py-4">{footer}</div>}
            </>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}
