import { Suspense, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Menu, Search } from 'lucide-react'
import { Outlet, useNavigate } from 'react-router-dom'
import { Kbd, Skeleton } from '@/components/ui/Feedback'
import { LogoMark } from '@/components/ui/Logo'
import { UploadDialog } from '@/components/documents/UploadDialog'
import { modKeyLabel, useHotkeys } from '@/hooks/useHotkeys'
import { systemApi } from '@/services/api'
import { useUploads } from '@/stores/uploads'
import { useUI } from '@/stores/ui'
import { CommandPalette } from './CommandPalette'
import { MobileNav } from './MobileNav'
import { NotificationBell } from './NotificationBell'
import { Onboarding } from './Onboarding'
import { Sidebar } from './Sidebar'
import { UserMenu } from './UserMenu'

export function AppShell() {
  const setCommandOpen = useUI((s) => s.setCommandOpen)
  const setMobileNavOpen = useUI((s) => s.setMobileNavOpen)
  const navigate = useNavigate()
  const setUploadOpen = useUploads((s) => s.setDialogOpen)
  const config = useQuery({ queryKey: ['config'], queryFn: systemApi.config, staleTime: Infinity })

  useEffect(() => {
    if (config.data) useUploads.getState().setMaxSizeMb(config.data.max_upload_size_mb)
  }, [config.data])

  useHotkeys([
    { combo: 'mod+k', handler: () => setCommandOpen(!useUI.getState().commandOpen) },
    { combo: 'mod+u', handler: () => setUploadOpen(true) },
    { combo: '/', handler: () => navigate('/search') },
  ])

  return (
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur sm:px-6">
          <button
            className="-ml-1.5 rounded-md p-1.5 text-muted hover:bg-surface-muted hover:text-text lg:hidden"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="size-5" />
          </button>
          <LogoMark className="size-6 lg:hidden" />
          <button
            onClick={() => setCommandOpen(true)}
            className="flex h-9 w-full max-w-md items-center gap-2.5 rounded-md border border-border bg-surface px-3 text-small text-subtle shadow-sm transition-colors hover:border-border-strong"
          >
            <Search className="size-4" aria-hidden />
            <span className="flex-1 text-left">Search or jump to…</span>
            <span className="hidden items-center gap-0.5 sm:flex">
              <Kbd>{modKeyLabel}</Kbd>
              <Kbd>K</Kbd>
            </span>
          </button>
          <div className="ml-auto flex items-center gap-2">
            {config.data?.demo_mode && (
              <a
                href={config.data.github_url || 'https://github.com/mygit72/Research-System'}
                target="_blank"
                rel="noreferrer"
                className="hidden items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-caption font-medium text-primary transition hover:bg-primary/20 sm:inline-flex"
                title="Public demonstration of Research Intelligence. Click to visit GitHub repository."
              >
                <span>Demo Mode</span>
                <span className="text-subtle">•</span>
                <span className="underline decoration-primary/40 underline-offset-2">GitHub</span>
              </a>
            )}
            <NotificationBell />
            <UserMenu />
          </div>
        </header>
        <main id="main" className="flex-1">
          <Suspense
            fallback={
              <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8" aria-busy="true" aria-label="Loading page">
                <Skeleton className="h-8 w-1/3" />
                <Skeleton className="mt-6 h-64 w-full" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </main>
      </div>
      <MobileNav />
      <CommandPalette />
      <Onboarding />
      <UploadDialog />
    </div>
  )
}
