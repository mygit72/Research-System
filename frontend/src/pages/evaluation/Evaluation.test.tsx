import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { evaluationApi } from '@/services/api'
import type { EvalDataset, EvalItem, EvalRun } from '@/types/api'
import { EvaluationPage } from './EvaluationPage'
import { RunPage } from './RunPage'

function wrap(children: ReactNode, path = '/evaluation', route = '/evaluation') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={children} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

const now = new Date().toISOString()
const dataset: EvalDataset = {
  id: 'ds1', name: 'My questions', description: '', generation: {}, created_at: now, updated_at: now,
  verified: 2, unverified: 1, runs: 2,
}
const evidence = { document_id: 'd1', version_id: 'v1', char_start: 0, char_end: 40, page: 3, quote: 'RRF fuses rankings.', title: 'Hybrid retrieval' }
const items: EvalItem[] = [
  { id: 'i1', dataset_id: 'ds1', question: 'How are rankings combined?', expected: [evidence], reference_answer: '', source: 'manual', status: 'verified', created_at: now },
  { id: 'i2', dataset_id: 'ds1', question: 'What does the paper report about adapters?', expected: [evidence], reference_answer: '', source: 'generated', status: 'unverified', created_at: now },
]

const run = (id: string, name: string, recall: number, over: Partial<EvalRun> = {}): EvalRun => ({
  id, dataset_id: 'ds1', name, kind: 'retrieval', config: { mode: id === 'a' ? 'hybrid' : 'keyword', rerank: true },
  status: 'ready', items_evaluated: 2, latency_ms: 400, error_message: null, created_at: now, progress: null,
  metrics: { 'recall@10': recall, 'precision@5': 0.2, mrr: recall, 'ndcg@10': recall, 'paper_recall@5': 1, latency_search_p50_ms: 120, latency_total_p95_ms: 150, tokens_input: 0, tokens_output: 0, cost_usd: 0, throughput_per_min: 30 },
  per_item: [
    { item_id: 'i1', question: 'How are rankings combined?', metrics: { 'recall@10': 1, mrr: 1 }, top: [{ title: 'Hybrid retrieval', page: 3, relevant: true }], latency_ms: { search: 100 } },
    { item_id: 'i3', question: 'Which rank works best?', metrics: { 'recall@10': recall === 1 ? 1 : 0, mrr: 0 }, top: [{ title: 'LoRA', page: 2, relevant: false }], latency_ms: { search: 120 } },
  ],
  ...over,
})

describe('EvaluationPage', () => {
  it('starts a run with the chosen configuration', async () => {
    vi.spyOn(evaluationApi, 'datasets').mockResolvedValue([dataset])
    vi.spyOn(evaluationApi, 'runs').mockResolvedValue([run('a', 'hybrid', 1)])
    const start = vi.spyOn(evaluationApi, 'startRun').mockResolvedValue(run('b', 'bm25', 0.5, { status: 'queued' }))
    render(wrap(<EvaluationPage />))
    expect(await screen.findByRole('link', { name: 'hybrid' })).toBeInTheDocument()
    await screen.findByRole('option', { name: 'My questions (2 questions)' })
    await userEvent.selectOptions(screen.getByLabelText('Dataset'), 'ds1')
    await userEvent.selectOptions(screen.getByLabelText('Retriever'), 'keyword')
    await userEvent.click(screen.getByLabelText('Rerank'))
    await userEvent.type(screen.getByLabelText('RRF k'), '30')
    await userEvent.click(screen.getByRole('button', { name: /^Run$/ }))
    expect(start).toHaveBeenCalledWith('ds1', { name: '', kind: 'retrieval', config: { mode: 'keyword', rerank: false, rrf_k: 30 } })
  })

  it('compares runs in a chart, a table with differences and per-question disagreements', async () => {
    const runs = { a: run('a', 'hybrid', 1), b: run('b', 'bm25', 0.5) }
    vi.spyOn(evaluationApi, 'run').mockImplementation(async (id: string) => runs[id as 'a' | 'b'])
    render(wrap(<EvaluationPage />, '/evaluation?view=compare&runs=a,b'))
    expect(await screen.findByRole('img', { name: /hybrid, bm25/ })).toBeInTheDocument()
    const row = screen.getAllByRole('row').find((r) => r.textContent?.startsWith('Recall@10'))!
    expect(within(row).getByText('1.000')).toBeInTheDocument()
    expect(within(row).getByText('-0.500')).toBeInTheDocument()
    expect(screen.getByText('Questions where the runs disagree (1)')).toBeInTheDocument()
    expect(screen.getByText('Which rank works best?')).toBeInTheDocument()
  })

  it('lists questions and accepts drafted ones', async () => {
    vi.spyOn(evaluationApi, 'datasets').mockResolvedValue([dataset])
    vi.spyOn(evaluationApi, 'items').mockResolvedValue(items)
    const update = vi.spyOn(evaluationApi, 'updateItem').mockResolvedValue({ ...items[1], status: 'verified' })
    render(wrap(<EvaluationPage />, '/evaluation?view=datasets'))
    expect(await screen.findByText('How are rankings combined?')).toBeInTheDocument()
    expect(screen.getByText('Questions (2) · 1 to review')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Accept: What does the paper report/ }))
    expect(update).toHaveBeenCalledWith('i2', { status: 'verified' })
  })
})

describe('RunPage', () => {
  it('shows metrics with explanations and per-question results', async () => {
    vi.spyOn(evaluationApi, 'run').mockResolvedValue(run('a', 'hybrid', 0.5))
    render(wrap(<RunPage />, '/evaluation/runs/a', '/evaluation/runs/:id'))
    expect(await screen.findByRole('heading', { name: 'hybrid' })).toBeInTheDocument()
    expect(screen.getByText(/Share of the expected evidence found in the top 10/)).toBeInTheDocument()
    expect(screen.getByText('found')).toBeInTheDocument()
    expect(screen.getByText('missed')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /How are rankings combined/ }))
    expect(screen.getByText(/Hybrid retrieval, p. 3 — expected evidence/)).toBeInTheDocument()
  })
})
