import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '@/lib/queryClient'
import { collectionsApi, projectsApi, watchesApi } from '@/services/api'
import type { DigestEntry, Watch, WatchRun } from '@/types/api'
import { WatchPage } from './WatchPage'

// The app's hooks invalidate the shared `queryClient` singleton directly (not via
// useQueryClient()), so the provider here must be that same instance for a mutation's
// invalidation to refetch what this page renders.
function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/watches/w1']}>
        <Routes>
          <Route path="/watches/:id" element={children} />
          <Route path="/papers/:id" element={<p>Opened paper</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  queryClient.clear()
})

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

const entry = (over: Partial<DigestEntry> = {}): DigestEntry => ({
  id: 'e1',
  run_id: 'r1',
  watch_id: 'w1',
  arxiv_id: '2501.00001',
  title: 'Low Rank Adapters at Scale',
  authors: [{ name: 'Ada Researcher', affiliation: null }],
  abstract: 'A study of adapters.',
  published: '2026-01-01',
  score: 0.72,
  blurb: null,
  document_id: null,
  import_status: 'pending',
  created_at: new Date().toISOString(),
  trace: {
    search_query: 'low rank adapters',
    searched_since: new Date().toISOString(),
    anchor_topic: 'low rank adapters',
    anchor_project_question: null,
    rank: 1,
    candidates_in_run: 5,
    relevance_threshold: 0.35,
  },
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
  candidates_found: 3,
  candidates_above_threshold: 1,
  imported_count: 0,
  error_message: null,
  report_id: null,
  ...over,
})

describe('WatchPage', () => {
  it('renders a digest entry with its blurb when present, and lets you add it to the library', async () => {
    vi.spyOn(watchesApi, 'get').mockResolvedValue(watch())
    vi.spyOn(watchesApi, 'runs').mockResolvedValue({ items: [run()], total: 1, limit: 20, offset: 0 })
    let imported = false
    vi.spyOn(watchesApi, 'digest').mockImplementation(async () => ({
      items: [
        imported
          ? entry({ import_status: 'imported', document_id: 'd1' })
          : entry({ blurb: 'Relevant because it studies adapters directly.' }),
      ],
      total: 1,
      limit: 20,
      offset: 0,
    }))
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])
    const importEntry = vi.spyOn(watchesApi, 'importEntry').mockImplementation(async () => {
      imported = true
      return entry({ import_status: 'imported', document_id: 'd1' })
    })

    render(wrap(<WatchPage />))
    expect(await screen.findByText('Low Rank Adapters at Scale')).toBeInTheDocument()
    expect(screen.getByText('Relevant because it studies adapters directly.')).toBeInTheDocument()
    expect(screen.getByText('72% match')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Add to library' }))
    expect(importEntry).toHaveBeenCalledWith('w1', 'e1')
    await vi.waitFor(() => expect(watchesApi.digest).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('link', { name: 'Added' })).toHaveAttribute('href', '/papers/d1')
  })

  it('omits the blurb line cleanly when there is none', async () => {
    vi.spyOn(watchesApi, 'get').mockResolvedValue(watch())
    vi.spyOn(watchesApi, 'runs').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(watchesApi, 'digest').mockResolvedValue({
      items: [entry()],
      total: 1,
      limit: 20,
      offset: 0,
    })
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])

    render(wrap(<WatchPage />))
    expect(await screen.findByText('Low Rank Adapters at Scale')).toBeInTheDocument()
    expect(screen.queryByText(/Relevant because/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to library' })).toBeInTheDocument()
  })

  it('shows "why this matched" from the entry trace', async () => {
    vi.spyOn(watchesApi, 'get').mockResolvedValue(watch())
    vi.spyOn(watchesApi, 'runs').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(watchesApi, 'digest').mockResolvedValue({
      items: [entry({ trace: { ...entry().trace, rank: 2, candidates_in_run: 7 } })],
      total: 1,
      limit: 20,
      offset: 0,
    })
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])

    render(wrap(<WatchPage />))
    await userEvent.click(await screen.findByText('Why this matched'))
    expect(screen.getAllByText('low rank adapters', { selector: 'dd' })).toHaveLength(2)
    expect(screen.getByText(/2 of 7 candidates found/)).toBeInTheDocument()
  })

  it('shows a link to the literature review when the latest run has one', async () => {
    vi.spyOn(watchesApi, 'get').mockResolvedValue(watch({ latest_run: run({ report_id: 'rep1' }) }))
    vi.spyOn(watchesApi, 'runs').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(watchesApi, 'digest').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])

    render(wrap(<WatchPage />))
    const link = await screen.findByRole('link', { name: /literature review/i })
    expect(link).toHaveAttribute('href', '/reviews/rep1')
  })

  it('has no literature review link when the latest run has none', async () => {
    vi.spyOn(watchesApi, 'get').mockResolvedValue(watch({ latest_run: run({ report_id: null }) }))
    vi.spyOn(watchesApi, 'runs').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(watchesApi, 'digest').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])

    render(wrap(<WatchPage />))
    await screen.findByText('Adapters')
    expect(screen.queryByRole('link', { name: /literature review/i })).not.toBeInTheDocument()
  })

  it('shows a copyable public link when the watch is public', async () => {
    vi.spyOn(watchesApi, 'get').mockResolvedValue(watch({ is_public: true }))
    vi.spyOn(watchesApi, 'runs').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(watchesApi, 'digest').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })

    render(wrap(<WatchPage />))
    expect(await screen.findByText(/\/w\/w1$/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /copy link/i }))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('/w/w1'))
  })
})
