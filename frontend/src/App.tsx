import { Suspense, lazy, useEffect } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { LogoMark } from '@/components/ui/Logo'
import { HelpPage } from '@/pages/HelpPage'
import { HomePage } from '@/pages/HomePage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { PapersPage } from '@/pages/PapersPage'
import { LoginPage } from '@/pages/auth/LoginPage'
import { RegisterPage } from '@/pages/auth/RegisterPage'
import { useAuth } from '@/stores/auth'
import { usePreferences } from '@/stores/preferences'

// Heavier pages load on first visit, keeping the initial bundle small.
const PaperPage = lazy(() => import('@/pages/paper/PaperPage').then((m) => ({ default: m.PaperPage })))
const SearchPage = lazy(() => import('@/pages/search/SearchPage').then((m) => ({ default: m.SearchPage })))
const ChatPage = lazy(() => import('@/pages/chat/ChatPage').then((m) => ({ default: m.ChatPage })))
const ComparePage = lazy(() => import('@/pages/compare/ComparePage').then((m) => ({ default: m.ComparePage })))
const ComparisonPage = lazy(() =>
  import('@/pages/compare/ComparisonPage').then((m) => ({ default: m.ComparisonPage })),
)
const CollectionsPage = lazy(() =>
  import('@/pages/collections/CollectionsPage').then((m) => ({ default: m.CollectionsPage })),
)
const CollectionPage = lazy(() =>
  import('@/pages/collections/CollectionPage').then((m) => ({ default: m.CollectionPage })),
)
const NotesPage = lazy(() => import('@/pages/NotesPage').then((m) => ({ default: m.NotesPage })))
const KnowledgePage = lazy(() =>
  import('@/pages/knowledge/KnowledgePage').then((m) => ({ default: m.KnowledgePage })),
)
const EntityPage = lazy(() => import('@/pages/knowledge/EntityPage').then((m) => ({ default: m.EntityPage })))
const AuthorPage = lazy(() => import('@/pages/knowledge/AuthorPage').then((m) => ({ default: m.AuthorPage })))
const ReportsPage = lazy(() => import('@/pages/reports/ReportsPage').then((m) => ({ default: m.ReportsPage })))
const ReportPage = lazy(() => import('@/pages/reports/ReportPage').then((m) => ({ default: m.ReportPage })))
const ProjectsPage = lazy(() => import('@/pages/projects/ProjectsPage').then((m) => ({ default: m.ProjectsPage })))
const ProjectPage = lazy(() => import('@/pages/projects/ProjectPage').then((m) => ({ default: m.ProjectPage })))
const WatchesPage = lazy(() => import('@/pages/watches/WatchesPage').then((m) => ({ default: m.WatchesPage })))
const WatchPage = lazy(() => import('@/pages/watches/WatchPage').then((m) => ({ default: m.WatchPage })))
const PublicWatchPage = lazy(() =>
  import('@/pages/watches/PublicWatchPage').then((m) => ({ default: m.PublicWatchPage })),
)
const EvaluationPage = lazy(() =>
  import('@/pages/evaluation/EvaluationPage').then((m) => ({ default: m.EvaluationPage })),
)
const RunPage = lazy(() => import('@/pages/evaluation/RunPage').then((m) => ({ default: m.RunPage })))
const UsagePage = lazy(() => import('@/pages/UsagePage').then((m) => ({ default: m.UsagePage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))

function SplashScreen() {
  return (
    <div className="flex min-h-dvh items-center justify-center" aria-busy="true" aria-label="Loading">
      <LogoMark className="size-9 animate-pulse" />
    </div>
  )
}

function RequireAuth() {
  const status = useAuth((s) => s.status)
  const location = useLocation()
  if (status === 'loading') return <SplashScreen />
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

function GuestOnly() {
  const status = useAuth((s) => s.status)
  if (status === 'loading') return <SplashScreen />
  if (status === 'authenticated') return <Navigate to="/" replace />
  return <Outlet />
}

export default function App() {
  const bootstrap = useAuth((s) => s.bootstrap)
  const user = useAuth((s) => s.user)
  const hydrate = usePreferences((s) => s.hydrateFromServer)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  // Server-side preferences win once the user is known (cross-device sync).
  useEffect(() => {
    if (user) hydrate(user.preferences)
  }, [user?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Routes>
      <Route
        path="/w/:id"
        element={
          <Suspense fallback={<SplashScreen />}>
            <PublicWatchPage />
          </Suspense>
        }
      />
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="/papers" element={<PapersPage />} />
          <Route path="/papers/:id" element={<PaperPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/chat/:id?" element={<ChatPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/compare/:id" element={<ComparisonPage />} />
          <Route path="/collections" element={<CollectionsPage />} />
          <Route path="/collections/:id" element={<CollectionPage />} />
          <Route path="/notes" element={<NotesPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/watches" element={<WatchesPage />} />
          <Route path="/watches/:id" element={<WatchPage />} />
          <Route path="/reviews" element={<ReportsPage />} />
          <Route path="/reviews/:id" element={<ReportPage />} />
          <Route path="/graph" element={<KnowledgePage />} />
          <Route path="/entities/:id" element={<EntityPage />} />
          <Route path="/authors/:key" element={<AuthorPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/evaluation/runs/:id" element={<RunPage />} />
          <Route path="/usage" element={<UsagePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
