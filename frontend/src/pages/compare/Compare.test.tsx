import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { comparisonCsv, comparisonMarkdown, compareReason } from '@/lib/compare'
import { comparisonsApi, documentsApi, systemApi } from '@/services/api'
import type { AIStatus, Comparison, ComparisonCell, DocumentDetail, EvidenceItem } from '@/types/api'
import { ComparePage } from './ComparePage'
import { ComparisonPage } from './ComparisonPage'

function wrap(children: ReactNode, path: string, route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={children} />
            <Route path="/compare/:id" element={<p>Opened comparison</p>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  )
}

const cell = (letter: string, text: string, status: ComparisonCell['status'] = 'supported', citations: number[] = []): ComparisonCell => ({
  document_id: `doc-${letter}`,
  letter,
  text,
  citations,
  status,
  label: status === 'not_reported' ? 'Not reported' : 'Well supported',
  explanation: '1 of 1 statement directly supported.',
  claims: [],
})

const source = (number: number, letter: string): EvidenceItem & { letter: string } => ({
  number,
  letter,
  chunk_id: `c${number}`,
  document: { id: `doc-${letter}`, title: letter === 'A' ? 'Low-Rank Adapters' : 'Hybrid Retrieval', year: 2023 },
  section_title: 'Experiments',
  page_start: number,
  page_end: number,
  char_start: 0,
  boxes: [],
  quote: 'We evaluate on MedQA.',
  score: 1,
})

function makeComparison(overrides: Partial<Comparison> = {}): Comparison {
  return {
    id: 'cmp-1',
    title: 'Low-Rank Adapters vs Hybrid Retrieval',
    kind: 'papers',
    status: 'ready',
    columns: [
      { document_id: 'doc-A', version_id: 'v1', letter: 'A', title: 'Low-Rank Adapters', year: 2023, authors_display: 'Wei', extraction_id: 'e1', deleted: false },
      { document_id: 'doc-B', version_id: 'v2', letter: 'B', title: 'Hybrid Retrieval', year: 2024, authors_display: 'Doe', extraction_id: 'e2', deleted: false },
    ],
    rows: [
      { key: 'dataset', title: 'Dataset', agreement: 'different', cells: [cell('A', 'MedQA and CaseHOLD [1].', 'supported', [1]), cell('B', 'SciQA [2].', 'supported', [2])] },
      { key: 'compute', title: 'Compute', agreement: 'partial', cells: [cell('A', '7B model on GPUs [1].', 'partial', [1]), cell('B', 'Not reported.', 'not_reported')] },
      { key: 'problem', title: 'Problem', agreement: 'similar', cells: [cell('A', 'Costly | slow "tuning" [1].', 'supported', [1]), cell('B', 'Costly tuning [2].', 'supported', [2])] },
    ],
    sources: [source(1, 'A'), source(2, 'B')],
    overview: {
      text: 'Paper A adapts language models [1]. Paper B retrieves passages [2].',
      citations: [1, 2],
      status: 'supported',
      label: 'Well supported',
      explanation: '2 of 2 statements directly supported.',
      claims: [],
    },
    support: { status: 'supported', label: 'Well supported', explanation: '5 of 6 statements directly supported.', verifier: 'nli', statements: 6, not_reported: ['Compute (B)'] },
    generation_config: { llm_model: 'qwen2.5:3b' },
    trace: { papers: [{ document_id: 'doc-A', cached: true }, { document_id: 'doc-B', cached: false }] },
    input_tokens: 1,
    output_tokens: 1,
    latency_ms: 61_000,
    error_message: null,
    error_hint: null,
    progress: null,
    stale: null,
    created_at: '2026-10-02T10:00:00Z',
    updated_at: '2026-10-02T10:01:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.spyOn(systemApi, 'aiStatus').mockResolvedValue({ llm: { ready: true } } as unknown as AIStatus)
})
afterEach(() => vi.restoreAllMocks())

describe('comparison export', () => {
  it('writes Markdown with the overview, an escaped table and cited sources', () => {
    const text = comparisonMarkdown(makeComparison())
    expect(text).toContain('# Low-Rank Adapters vs Hybrid Retrieval')
    expect(text).toContain('| | A. Low-Rank Adapters (2023) | B. Hybrid Retrieval (2024) |')
    expect(text).toContain('| **Problem** | Costly \\| slow "tuning" [1]. | Costly tuning [2]. |')
    expect(text).toContain('[2] B. Hybrid Retrieval, p. 2 (Experiments)')
  })

  it('writes CSV with quoted cells', () => {
    const rows = comparisonCsv(makeComparison()).split('\r\n')
    expect(rows[0]).toBe('"Category","A. Low-Rank Adapters (2023)","B. Hybrid Retrieval (2024)"')
    expect(rows).toContain('"Problem","Costly | slow ""tuning"" [1].","Costly tuning [2]."')
  })

  it('only lets ready, indexed papers be compared', () => {
    expect(compareReason({ status: 'ready', index_status: 'indexed' })).toBeNull()
    expect(compareReason({ status: 'processing', index_status: 'pending' })).toMatch(/processed/)
    expect(compareReason({ status: 'ready', index_status: 'failed' })).toMatch(/indexing/)
  })
})

describe('ComparisonPage', () => {
  it('shows the overview, the table, “Not reported” and highlights differences', async () => {
    vi.spyOn(comparisonsApi, 'get').mockResolvedValue(makeComparison())
    render(wrap(<ComparisonPage />, '/compare/cmp-1', '/compare/:id'))
    expect(await screen.findByRole('heading', { name: 'Low-Rank Adapters vs Hybrid Retrieval' })).toBeInTheDocument()
    expect(screen.getByText(/Paper A adapts language models/)).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('Not reported')).toBeInTheDocument()
    expect(screen.getByText(/1 paper\(s\) reused from earlier comparisons/)).toBeInTheDocument()

    const rowOf = (name: string) => within(table).getByRole('rowheader', { name: new RegExp(name) }).closest('tr')!
    expect(rowOf('Dataset')).not.toHaveClass('bg-warning-soft/60')
    await userEvent.click(screen.getByRole('button', { name: 'Highlight differences' }))
    expect(rowOf('Dataset')).toHaveClass('bg-warning-soft/60')
    expect(rowOf('Compute')).toHaveClass('bg-warning-soft/60')
    expect(rowOf('Problem')).not.toHaveClass('bg-warning-soft/60')
    expect(within(rowOf('Dataset')).getByText('Differs')).toBeInTheDocument()
  })

  it('pins a paper column next to the categories', async () => {
    vi.spyOn(comparisonsApi, 'get').mockResolvedValue(makeComparison())
    render(wrap(<ComparisonPage />, '/compare/cmp-1', '/compare/:id'))
    const headers = async () => (await screen.findAllByRole('columnheader')).map((h) => h.textContent)
    expect((await headers())[1]).toMatch(/^ALow-Rank Adapters/)
    await userEvent.click(screen.getByRole('button', { name: 'Pin Hybrid Retrieval' }))
    expect((await headers())[1]).toMatch(/^BHybrid Retrieval/)
    expect(screen.getByRole('button', { name: 'Unpin Hybrid Retrieval' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows progress while papers are read, and failures with their hint', async () => {
    vi.spyOn(comparisonsApi, 'get').mockResolvedValueOnce(
      makeComparison({ status: 'running', rows: [], overview: null, progress: { stage: 'comparing', detail: 'Reading the method of “LoRA” (paper 1 of 2)', progress: 0.25 } }),
    )
    const { unmount } = render(wrap(<ComparisonPage />, '/compare/cmp-1', '/compare/:id'))
    expect(await screen.findByText('Reading the method of “LoRA” (paper 1 of 2)…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Highlight differences' })).not.toBeInTheDocument()
    unmount()

    const get = vi.spyOn(comparisonsApi, 'get').mockResolvedValue(
      makeComparison({ status: 'failed', rows: [], overview: null, error_message: 'Can’t reach Ollama.', error_hint: 'Start Ollama' }),
    )
    const create = vi.spyOn(comparisonsApi, 'create').mockResolvedValue(makeComparison({ id: 'cmp-2', status: 'queued' }))
    render(wrap(<ComparisonPage />, '/compare/cmp-1', '/compare/:id'))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('Start Ollama')).toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(create).toHaveBeenCalledWith({ document_ids: ['doc-A', 'doc-B'], kind: 'papers', force: false })
    await vi.waitFor(() => expect(get).toHaveBeenCalledWith('cmp-2')) // moved to the new comparison
  })
})

describe('ComparePage', () => {
  const doc = (id: string, title: string, extra: Partial<DocumentDetail> = {}) =>
    ({ id, title, status: 'ready', index_status: 'indexed', authors_display: 'Wei', year: 2023, ...extra }) as DocumentDetail

  it('compares the papers from the link and opens the result', async () => {
    vi.spyOn(comparisonsApi, 'list').mockResolvedValue([])
    vi.spyOn(documentsApi, 'get').mockImplementation(async (id) => doc(id, id === 'a' ? 'Paper One' : 'Paper Two'))
    const create = vi.spyOn(comparisonsApi, 'create').mockResolvedValue(makeComparison({ id: 'cmp-9' }))
    render(wrap(<ComparePage />, '/compare?papers=a,b&kind=methodology', '/compare'))
    expect(await screen.findByText('Paper Two')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Methodology/ })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(create).toHaveBeenCalledWith({ document_ids: ['a', 'b'], kind: 'methodology' })
    expect(await screen.findByText('Opened comparison')).toBeInTheDocument()
  })

  it('needs at least two papers', async () => {
    vi.spyOn(comparisonsApi, 'list').mockResolvedValue([])
    vi.spyOn(documentsApi, 'get').mockResolvedValue(doc('a', 'Paper One'))
    render(wrap(<ComparePage />, '/compare?papers=a', '/compare'))
    expect(await screen.findByText('Add 1 more paper to compare.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Compare' })).toBeDisabled()
    expect(await screen.findByText('No comparisons yet')).toBeInTheDocument()
  })
})
