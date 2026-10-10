import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { searchApi } from '@/services/api'
import type { SearchFacets, SearchHit, SearchResponse } from '@/types/api'
import { SearchPage } from './SearchPage'

const facets: SearchFacets = {
  papers: 2,
  indexed_papers: 2,
  year_min: 2023,
  year_max: 2024,
  doc_types: [{ value: 'pdf', count: 2 }],
  authors: [{ value: 'Maya Lindqvist', count: 1 }],
  section_kinds: [
    { value: 'method', count: 4 },
    { value: 'references', count: 2 },
  ],
  suggestions: ['hybrid search', 'LoRA'],
  collections: [],
  tags: [],
}

const text = 'The two ranked lists are fused with reciprocal rank fusion before reranking.'
const hit = (chunk: string, doc: string, title: string, score: number): SearchHit => ({
  rank: 1,
  chunk_id: chunk,
  document: {
    id: doc,
    title,
    authors_display: 'M. Lindqvist',
    year: 2024,
    doc_type: 'pdf',
    venue: null,
  },
  text,
  kind: 'text',
  section_title: '3 Method',
  section_kind: 'method',
  page_start: 2,
  page_end: 2,
  char_start: 500,
  boxes: [],
  score,
  score_kind: 'rrf',
  matched_by: ['bm25', 'dense'],
  retriever_ranks: { bm25: 1, dense: 2 },
  fused_rank: 1,
  highlights: [[36, 58]],
  snippet: [0, text.length],
})

const response = (overrides: Partial<SearchResponse> = {}): SearchResponse => ({
  query: 'rank fusion',
  mode: 'hybrid',
  status: 'ok',
  results: [
    hit('c1', 'd1', 'Hybrid Retrieval', 0.032),
    hit('c2', 'd1', 'Hybrid Retrieval', 0.03),
    hit('c3', 'd2', 'LoRA', 0.016),
  ],
  retrievers: ['bm25', 'dense'],
  reranker: null,
  searched_papers: 2,
  warnings: [],
  timings_ms: { total: 12.4 },
  trace: null,
  ...overrides,
})

function Location() {
  const location = useLocation()
  return <div data-testid="location">{location.search}</div>
}

function renderAt(url: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route
              path="/search"
              element={
                <>
                  <SearchPage />
                  <Location />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.spyOn(searchApi, 'facets').mockResolvedValue(facets)
  try {
    localStorage.clear()
  } catch {
    /* jsdom */
  }
})
afterEach(() => vi.restoreAllMocks())

describe('SearchPage', () => {
  it('shows results grouped by paper with highlighted matches', async () => {
    const search = vi.spyOn(searchApi, 'search').mockResolvedValue(response())
    renderAt('/search?q=rank+fusion')
    const first = await screen.findByRole('article', {
      name: 'Hybrid Retrieval',
    })
    expect(within(first).getByText('reciprocal rank fusion').tagName).toBe('MARK')
    expect(within(first).getByText('1 more matching passage in this paper')).toBeInTheDocument()
    expect(within(first).getByRole('link', { name: /Open in paper/ })).toHaveAttribute(
      'href',
      '/papers/d1?tab=paper&page=2&char=500',
    )
    expect(screen.getByRole('article', { name: 'LoRA' })).toBeInTheDocument()
    expect(screen.getByText(/3 passages in 2 papers/)).toBeInTheDocument()
    expect(search).toHaveBeenCalledWith(
      expect.objectContaining({
        query: 'rank fusion',
        mode: 'hybrid',
        limit: 20,
      }),
      expect.anything(),
    )
  })

  it('offers suggestions from the library before searching', async () => {
    vi.spyOn(searchApi, 'search').mockResolvedValue(response())
    renderAt('/search')
    await userEvent.click(await screen.findByRole('button', { name: 'LoRA' }))
    expect(screen.getByTestId('location')).toHaveTextContent('?q=LoRA')
    expect(screen.getByRole('searchbox')).toHaveValue('LoRA')
  })

  it('keeps filters and mode in the URL', async () => {
    const search = vi.spyOn(searchApi, 'search').mockResolvedValue(response())
    renderAt('/search?q=rank')
    await userEvent.click(await screen.findByRole('checkbox', { name: /Maya Lindqvist/ }))
    expect(screen.getByTestId('location')).toHaveTextContent('author=Maya+Lindqvist')
    expect(search).toHaveBeenLastCalledWith(
      expect.objectContaining({ filters: { authors: ['Maya Lindqvist'] } }),
      expect.anything(),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Advanced search options' }))
    await userEvent.click(screen.getByRole('radio', { name: 'Keyword' }))
    expect(screen.getByTestId('location')).toHaveTextContent('mode=keyword')
  })

  it('shows fused results first, then swaps in the reranked order', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => (release = resolve))
    const fusedResponse = response()
    const rerankedResponse = response({
      reranker: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
      results: [
        { ...hit('c3', 'd2', 'LoRA', 0.91), score_kind: 'rerank', fused_rank: 3 },
        { ...hit('c1', 'd1', 'Hybrid Retrieval', 0.42), score_kind: 'rerank', fused_rank: 1 },
      ],
    })
    const search = vi.spyOn(searchApi, 'search').mockImplementation(async (body) => {
      if (body.rerank === false) return fusedResponse
      await gate // the reranker is slower
      return rerankedResponse
    })
    renderAt('/search?q=rank+fusion')
    const titles = () =>
      screen.getAllByRole('article').map((a) => a.getAttribute('aria-labelledby'))
    await screen.findByRole('article', { name: 'Hybrid Retrieval' })
    expect(titles()[0]).toBe('result-c1') // fused order
    expect(screen.getByText('Refining the order…')).toBeInTheDocument()
    release()
    expect(await screen.findByText('Reranked')).toBeInTheDocument()
    expect(titles()[0]).toBe('result-c3') // reranked order
    expect(screen.queryByText('Refining the order…')).not.toBeInTheDocument()
    expect(search).toHaveBeenCalledWith(
      expect.objectContaining({ rerank: false }),
      expect.anything(),
    )
    expect(search).toHaveBeenCalledWith(
      expect.not.objectContaining({ rerank: false }),
      expect.anything(),
    )
  })

  it('skips the reranker when it is turned off', async () => {
    const search = vi.spyOn(searchApi, 'search').mockResolvedValue(response())
    renderAt('/search?q=rank&rerank=0')
    await screen.findByRole('article', { name: 'Hybrid Retrieval' })
    expect(search).toHaveBeenCalledTimes(1)
    expect(search).toHaveBeenCalledWith(
      expect.objectContaining({ rerank: false }),
      expect.anything(),
    )
    expect(screen.getByRole('checkbox', { name: 'Rerank results' })).not.toBeChecked()
  })

  it('explains empty results and warnings', async () => {
    vi.spyOn(searchApi, 'search').mockResolvedValue(
      response({
        status: 'no_results',
        results: [],
        mode: 'keyword',
        warnings: ['The embedding model couldn’t be loaded. Showing keyword matches only.'],
      }),
    )
    renderAt('/search?q=zzz&mode=keyword')
    expect(await screen.findByText(/No passages match/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use hybrid search' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('keyword matches only')
  })

  it('shows an upload prompt when the library is empty', async () => {
    vi.spyOn(searchApi, 'facets').mockResolvedValue({
      ...facets,
      papers: 0,
      indexed_papers: 0,
    })
    renderAt('/search')
    expect(await screen.findByText('Nothing to search yet.')).toBeInTheDocument()
  })
})
