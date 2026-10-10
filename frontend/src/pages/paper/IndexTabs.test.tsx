import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { documentsApi } from '@/services/api'
import type { ChunkInfo, DocumentDetail } from '@/types/api'
import { PassagesTab, SearchIndexCard } from './IndexTabs'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function makeDoc(overrides: Partial<DocumentDetail>): DocumentDetail {
  return {
    id: 'doc-1',
    status: 'ready',
    index_status: 'indexed',
    index_error: null,
    processing: null,
    version: {
      chunk_count: 15,
      chunking_strategy: 'section_aware',
      embedding_model: 'BAAI/bge-small-en-v1.5',
      indexed_at: null,
    },
    ...overrides,
  } as unknown as DocumentDetail
}

afterEach(() => vi.restoreAllMocks())

describe('SearchIndexCard', () => {
  it('shows how an indexed paper was indexed', () => {
    render(wrap(<SearchIndexCard doc={makeDoc({})} />))
    expect(screen.getByText('Searchable')).toBeInTheDocument()
    expect(screen.getByText('Section-aware')).toBeInTheDocument()
    expect(screen.getByText('BAAI/bge-small-en-v1.5')).toBeInTheDocument()
  })

  it('explains a failure, keeps the paper readable, and retries', async () => {
    const reindex = vi.spyOn(documentsApi, 'reindex').mockResolvedValue({} as never)
    const doc = makeDoc({ index_status: 'failed', index_error: 'The embedding model couldn’t be loaded.' })
    render(wrap(<SearchIndexCard doc={doc} />))
    expect(screen.getByText('Not searchable')).toBeInTheDocument()
    expect(screen.getByText(/You can read this paper/)).toBeInTheDocument()
    expect(screen.getByText(/couldn’t be loaded/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry indexing' }))
    expect(reindex).toHaveBeenCalledWith('doc-1')
  })
})

describe('PassagesTab', () => {
  const chunk = (index: number, tokens: number, page: number): ChunkInfo =>
    ({
      id: `c${index}`,
      chunk_index: index,
      kind: 'text',
      strategy: 'section_aware',
      text: `Passage ${index}`,
      context_header: 'Paper › Method',
      section_title: 'Method',
      page_start: page,
      page_end: page,
      token_count: tokens,
      boxes: [[page, 10, 20, 30, 40]],
    }) as unknown as ChunkInfo

  it('summarizes passages and opens one in the reader', async () => {
    vi.spyOn(documentsApi, 'chunks').mockResolvedValue({
      items: [chunk(0, 40, 1), chunk(1, 120, 2)],
      total: 2,
      limit: 500,
      offset: 0,
    })
    const onNavigate = vi.fn()
    render(wrap(<PassagesTab doc={makeDoc({})} onNavigate={onNavigate} />))
    expect(await screen.findByText('Passage 1')).toBeInTheDocument()
    expect(screen.getByText(/40–120 tokens \(avg 80\)/)).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Show in paper' })[1])
    expect(onNavigate).toHaveBeenCalledWith(2, [[2, 10, 20, 30, 40]])
  })

  it('has an empty state before indexing', () => {
    render(wrap(<PassagesTab doc={makeDoc({ index_status: 'pending' })} onNavigate={() => {}} />))
    expect(screen.getByRole('heading', { name: 'No passages yet' })).toBeInTheDocument()
  })
})
