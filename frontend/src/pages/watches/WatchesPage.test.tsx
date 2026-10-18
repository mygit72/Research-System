import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { collectionsApi, projectsApi, watchesApi } from '@/services/api'
import { ApiError } from '@/services/http'
import type { Watch, WatchRun } from '@/types/api'
import { WatchesPage } from './WatchesPage'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

const watch = (over: Partial<Watch> = {}): Watch => ({
  id: 'w1',
  name: 'Adapters',
  query: 'low rank adapters',
  collection_id: null,
  project_id: null,
  interval_hours: 24,
  relevance_threshold: 0.35,
  auto_import: false,
  synthesize: false,
  is_public: false,
  status: 'active',
  last_searched_at: null,
  next_run_at: new Date().toISOString(),
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  latest_run: null,
  ...over,
})

const run = (over: Partial<WatchRun> = {}): WatchRun => ({
  id: 'r1',
  watch_id: 'w1',
  status: 'succeeded',
  trigger: 'manual',
  created_at: new Date().toISOString(),
  started_at: null,
  finished_at: null,
  candidates_found: 5,
  candidates_above_threshold: 2,
  imported_count: 1,
  error_message: null,
  report_id: null,
  ...over,
})

describe('WatchesPage', () => {
  it('shows an empty state with no watches', async () => {
    vi.spyOn(watchesApi, 'list').mockResolvedValue([])
    render(wrap(<WatchesPage />))
    expect(await screen.findByText('No watches yet')).toBeInTheDocument()
  })

  it('shows a watch card with its latest-run summary and status', async () => {
    vi.spyOn(watchesApi, 'list').mockResolvedValue([watch({ latest_run: run() })])
    render(wrap(<WatchesPage />))
    expect(await screen.findByText('Adapters')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText(/found 2 of 5, added 1/)).toBeInTheDocument()
  })

  it('disables "Run now" while a run is already queued, and surfaces a 409 error', async () => {
    vi.spyOn(watchesApi, 'list').mockResolvedValue([
      watch({
        latest_run: run({
          status: 'queued',
          candidates_found: 0,
          candidates_above_threshold: 0,
          imported_count: 0,
        }),
      }),
    ])
    render(wrap(<WatchesPage />))
    expect(await screen.findByRole('button', { name: 'Run now' })).toBeDisabled()
  })

  it('recovers the "Run now" button after a 409 (a run already in flight)', async () => {
    vi.spyOn(watchesApi, 'list').mockResolvedValue([watch()])
    const runNowSpy = vi.spyOn(watchesApi, 'runNow').mockRejectedValue(
      new ApiError(409, { code: 'conflict', message: 'This watch already has a run in progress.' }),
    )
    render(wrap(<WatchesPage />))
    const runNow = await screen.findByRole('button', { name: 'Run now' })
    await userEvent.click(runNow)
    expect(runNowSpy).toHaveBeenCalledTimes(1)
    await vi.waitFor(() => expect(runNow).not.toBeDisabled())
  })

  it('opens the create dialog from the empty state', async () => {
    vi.spyOn(watchesApi, 'list').mockResolvedValue([])
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])
    render(wrap(<WatchesPage />))
    await screen.findByText('No watches yet')
    const [button] = screen.getAllByRole('button', { name: 'New watch' })
    await userEvent.click(button)
    expect(screen.getByRole('dialog', { name: 'New watch' })).toBeInTheDocument()
  })
})
