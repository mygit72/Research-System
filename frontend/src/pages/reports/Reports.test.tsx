import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { collectionsApi, reportsApi } from '@/services/api'
import type { Report } from '@/types/api'
import { ReportPage } from './ReportPage'
import { ReportsPage } from './ReportsPage'

function wrap(children: ReactNode, path = '/reviews', route = '/reviews') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={children} />
            <Route path="/reviews/:id" element={<p>Opened report</p>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

const source = (n: number, title: string) => ({
  number: n,
  chunk_id: `c${n}`,
  document: { id: `d${n}`, title, year: 2024 },
  section_title: 'Results',
  page_start: 4,
  page_end: 4,
  char_start: 0,
  boxes: [],
  quote: `Passage ${n} text.`,
})

const ready = (over: Partial<Report> = {}): Report => ({
  id: 'r1',
  kind: 'review',
  title: 'Parameter-efficient fine-tuning',
  query: 'Parameter-efficient fine-tuning',
  status: 'ready',
  document_ids: ['d1', 'd2'],
  collection_id: null,
  error_message: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  edited_at: null,
  params: { depth: 'standard' },
  sources: [source(1, 'LoRA paper'), source(2, 'Adapters paper')],
  support: { status: 'partial', statements: 3, counts: { supported: 2, partial: 1 }, verifier: 'nli', explanation: '2 of 3 written statements are directly supported by the passages they cite.' },
  trace: { summaries_written: ['d1'] },
  generation_config: { llm_model: 'qwen2.5:3b' },
  input_tokens: 10,
  output_tokens: 10,
  latency_ms: 1000,
  progress: null,
  error_hint: null,
  sections: [
    {
      key: 'overview', title: 'Overview', kind: 'text', text: 'LoRA trains low-rank updates [1].',
      citations: [1], claims: [{ text: 'LoRA trains low-rank updates [1].', citations: [1], status: 'supported', entailment: 0.9 }],
      status: 'supported', label: 'Well supported', origin: 'generated',
    },
    {
      key: 'comparison', title: 'Comparison of approaches', kind: 'table', text: '', citations: [2], claims: [],
      status: 'derived', label: 'Results are the papers’ verified summary statements', origin: 'derived',
      data: { rows: [{ document: { id: 'd2', title: 'Adapters paper', year: 2019 }, approach: 'PEFT', datasets: ['GLUE'], metrics: ['Accuracy'], result: 'Within 0.4 points.', citations: [2] }] },
    },
    {
      key: 'disagreements', title: 'Potential disagreements', kind: 'disagreements', text: '', citations: [1, 2], claims: [],
      status: 'derived', label: 'Flagged by the entailment model; not a judgement of which paper is right', origin: 'derived',
      data: { items: [{
        claim_a: { document: { id: 'd1', title: 'LoRA paper', year: 2021 }, text: 'LoRA improves GLUE.', field: 'results', citations: [1] },
        claim_b: { document: { id: 'd2', title: 'Adapters paper', year: 2019 }, text: 'LoRA does not improve GLUE.', field: 'results', citations: [2] },
        shared: ['GLUE'], differences: { model: { a: ['RoBERTa'], b: ['BERT'] } }, score: 0.91, detector: 'nli',
        label: 'Potential disagreement', note: 'The papers may differ in setup.',
      }] },
    },
    {
      key: 'gaps', title: 'Limitations and research gaps', kind: 'gaps', text: '', citations: [1], claims: [],
      status: 'derived', label: 'labels', origin: 'derived',
      data: {
        gaps: [
          { id: 'G1', kind: 'stated', origin: 'Stated by the authors', title: 'Recurring limitation: english', text: 'Only English.',
            papers: [{ id: 'd1', title: 'LoRA paper', year: 2021 }],
            statements: [{ document: { id: 'd1', title: 'LoRA paper', year: 2021 }, field: 'limitations', text: 'Only English data.', citations: [1] }] },
          { id: 'G2', kind: 'combination', origin: 'System-generated synthesis', title: 'Untested here: LoRA on SQuAD', text: 'None evaluates it.',
            papers: [{ id: 'd2', title: 'Adapters paper', year: 2019 }], statements: [] },
        ],
        directions: [{ text: 'Evaluate LoRA on multilingual data.', based_on: ['G1'], papers: [], origin: 'System-generated synthesis' }],
      },
    },
  ],
  ...over,
}) // fmt: skip

describe('ReportsPage', () => {
  it('starts a literature review from a topic and opens it', async () => {
    vi.spyOn(reportsApi, 'list').mockResolvedValue([])
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    const create = vi.spyOn(reportsApi, 'create').mockResolvedValue(ready({ status: 'queued' }))
    render(wrap(<ReportsPage />))
    const button = await screen.findByRole('button', { name: 'Generate review' })
    expect(button).toBeDisabled()
    await userEvent.type(screen.getByRole('textbox', { name: /Topic/ }), 'adapters')
    await userEvent.click(screen.getByRole('radio', { name: 'Brief up to 6 papers' }))
    await userEvent.click(button)
    expect(create).toHaveBeenCalledWith('review', { topic: 'adapters', depth: 'brief' })
    expect(await screen.findByText('Opened report')).toBeInTheDocument()
  })

  it('asks deep research for a question and limits', async () => {
    vi.spyOn(reportsApi, 'list').mockResolvedValue([])
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    const create = vi.spyOn(reportsApi, 'create').mockResolvedValue(ready({ kind: 'deep_research' }))
    render(wrap(<ReportsPage />, '/reviews?kind=deep_research'))
    await userEvent.type(await screen.findByRole('textbox', { name: /Research question/ }), 'How is RAG evaluated today?')
    await userEvent.click(screen.getByRole('button', { name: 'Start research' }))
    expect(create).toHaveBeenCalledWith('deep_research', { question: 'How is RAG evaluated today?', max_steps: 16, timeout_seconds: 900 })
  })
})

describe('ReportPage', () => {
  it('shows sections by kind, labels where gaps come from, and never picks a side', async () => {
    vi.spyOn(reportsApi, 'get').mockResolvedValue(ready())
    render(wrap(<ReportPage />, '/reviews/r1', '/reviews/:id'))
    expect(await screen.findByRole('heading', { level: 1, name: 'Parameter-efficient fine-tuning' })).toBeInTheDocument()
    expect(screen.getByText(/2 of 3 written statements/)).toBeInTheDocument()
    expect(screen.getByText(/1 paper summary was written for this report/)).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText(/Within 0.4 points/)).toBeInTheDocument()
    expect(screen.getByText(/Potential disagreement about GLUE/)).toBeInTheDocument()
    expect(screen.getByText(/first uses RoBERTa; second uses BERT/)).toBeInTheDocument()
    const gaps = screen.getByRole('region', { name: 'Limitations and research gaps' })
    expect(within(gaps).getAllByText('Stated by the authors')[0]).toBeInTheDocument()
    expect(within(gaps).getAllByText('System-generated synthesis').length).toBeGreaterThan(1)
    expect(within(gaps).getByText(/Evaluate LoRA on multilingual data/)).toBeInTheDocument()
  })

  it('edits written text and exports', async () => {
    vi.spyOn(reportsApi, 'get').mockResolvedValue(ready())
    const update = vi.spyOn(reportsApi, 'update').mockResolvedValue(ready({ edited_at: new Date().toISOString() }))
    render(wrap(<ReportPage />, '/reviews/r1', '/reviews/:id'))
    await userEvent.click(await screen.findByRole('button', { name: /Edit/ }))
    const text = screen.getByRole('textbox', { name: 'Text of “Overview”' })
    await userEvent.clear(text)
    await userEvent.type(text, 'My intro.')
    expect(screen.queryByRole('textbox', { name: /Comparison/ })).not.toBeInTheDocument() // built from data
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    expect(update).toHaveBeenCalledWith('r1', { sections: [{ key: 'overview', text: 'My intro.' }] })
  })

  it('shows progress through the stages while writing', async () => {
    vi.spyOn(reportsApi, 'get').mockResolvedValue(
      ready({ status: 'running', sections: [], progress: { stage: 'grouping', detail: 'Grouping the research', progress: 0.6 } }),
    )
    render(wrap(<ReportPage />, '/reviews/r1', '/reviews/:id'))
    expect(await screen.findByText('Grouping the research')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Report progress' })).toHaveAttribute('aria-valuenow', '60')
    expect(screen.getByText('Finding relevant papers')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument()
  })
})
