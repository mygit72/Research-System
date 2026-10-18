import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { publicApi } from '@/services/api'
import type { PublicDigestEntry, PublicWatch } from '@/types/api'
import { PublicWatchPage } from './PublicWatchPage'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/w/w1']}>
        <Routes>
          <Route path="/w/:id" element={children} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

const watch: PublicWatch = {
  id: 'w1',
  name: 'Adapters',
  query: 'low rank adapters',
  status: 'active',
  created_at: new Date().toISOString(),
}

const entry: PublicDigestEntry = {
  id: 'e1',
  arxiv_id: '2501.00001',
  title: 'Low Rank Adapters at Scale',
  authors: [{ name: 'Ada Researcher', affiliation: null }],
  abstract: 'A study of adapters.',
  published: '2026-01-01',
  score: 0.72,
  blurb: 'Directly relevant.',
  created_at: new Date().toISOString(),
}

describe('PublicWatchPage', () => {
  it('renders a public watch and its digest with no login chrome', async () => {
    vi.spyOn(publicApi, 'getWatch').mockResolvedValue(watch)
    vi.spyOn(publicApi, 'getDigest').mockResolvedValue({
      items: [entry],
      total: 1,
      limit: 20,
      offset: 0,
    })

    render(wrap(<PublicWatchPage />))
    expect(await screen.findByText('Adapters')).toBeInTheDocument()
    expect(screen.getByText('low rank adapters')).toBeInTheDocument()
    expect(await screen.findByText('Low Rank Adapters at Scale')).toBeInTheDocument()
    expect(screen.getByText('Directly relevant.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add to library/i })).not.toBeInTheDocument()
  })

  it('shows an error state when the watch is not public (404)', async () => {
    vi.spyOn(publicApi, 'getWatch').mockRejectedValue(new Error('Not found'))
    render(wrap(<PublicWatchPage />))
    expect(await screen.findByText("This watch isn't available")).toBeInTheDocument()
  })
})
