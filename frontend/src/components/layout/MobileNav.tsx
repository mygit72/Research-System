import * as RadixDialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { Logo } from '@/components/ui/Logo'
import { useUI } from '@/stores/ui'
import { SidebarContent } from './Sidebar'

/** Slide-in navigation drawer for tablet and mobile (< lg). */
export function MobileNav() {
  const open = useUI((s) => s.mobileNavOpen)
  const setOpen = useUI((s) => s.setMobileNavOpen)
  return (
    <RadixDialog.Root open={open} onOpenChange={setOpen}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/40 animate-fade-in lg:hidden" />
        <RadixDialog.Content className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-border bg-surface shadow-lg animate-fade-in lg:hidden">
          <RadixDialog.Title className="sr-only">Navigation</RadixDialog.Title>
          <RadixDialog.Description className="sr-only">Main navigation menu</RadixDialog.Description>
          <div className="flex h-14 items-center justify-between px-4">
            <Logo />
            <RadixDialog.Close
              aria-label="Close navigation"
              className="rounded-md p-1.5 text-muted hover:bg-surface-muted hover:text-text"
            >
              <X className="size-4" />
            </RadixDialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto py-2">
            <SidebarContent collapsed={false} onNavigate={() => setOpen(false)} />
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}
