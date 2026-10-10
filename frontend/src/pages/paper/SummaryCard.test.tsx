import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { summaryMarkdown } from '@/lib/summary'
import { summariesApi, systemApi } from '@/services/api'
import type { AIStatus, DocumentDetail, EvidenceItem, PaperSummary, SummarySection } from '@/types/api'
import { SummaryCard } from './SummaryCard'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  )
}

const doc = {
  id: 'doc-1',
  title: 'Low-Rank Adapters',
  status: 'ready',
  index_status: 'indexed',
} as unknown as DocumentDetail

const source = {
  number: 1,
  chunk_id: 'c1',
  document: { id: 'doc-1', title: 'Low-Rank Adapters', year: 2023 },
  section_title: '6 Limitations',
  page_start: 3,
  page_end: 3,
  char_start: 900,
  boxes: [[3, 10, 10, 200, 40]] as EvidenceItem['boxes'],
  quote: 'We only evaluated models up to seven billion parameters.',
  score: 1.2,
}

const section = (key: SummarySection['key'], title: string, text: string, status: SummarySection['status'] = 'supported'): SummarySection => ({
  key,
  title,
  text,
  citations: /\[1\]/.test(text) ? [1] : [],
  invalid_citations: [],
  status,
  label: status === 'supported' ? 'Well supported' : status === 'not_reported' ? 'Not reported' : 'Partially supported',
  explanation: '1 of 1 statement directly supported.',
  claims: [],
})

function makeSummary(overrides: Partial<PaperSummary> = {}): PaperSummary {
  return {
    id: 's1',
    document_id: 'doc-1',
    version_id: 'v1',
    status: 'ready',
    sections: [
      section('problem', 'Problem', 'Full fine-tuning is expensive [1].'),
      section('dataset', 'Dataset', 'Not reported.', 'not_reported'),
      section('limitations', 'Limitations', 'Only models up to 7B were evaluated [1].', 'partial'),
      section('takeaway', 'One-line takeaway', 'Low-rank adapters are cheap and accurate [1].'),
    ],
    sources: [source],
    support: {
      status: 'supported',
      label: 'Well supported',
      explanation: '3 of 3 statements directly supported.',
      verifier: 'lexical-coverage-v1',
      statements: 3,
      not_reported: ['Dataset'],
    },
    generation_config: { llm_model: 'qwen2.5:3b' },
    trace: {},
    input_tokens: 2000,
    output_tokens: 300,
    latency_ms: 42_000,
    error_message: null,
    error_hint: null,
    progress: null,
    stale: null,
    previous: null,
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:01:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.spyOn(systemApi, 'aiStatus').mockResolvedValue({ llm: { ready: true } } as unknown as AIStatus)
})
afterEach(() => vi.restoreAllMocks())

describe('SummaryCard', () => {
  it('offers to generate a summary when there is none', async () => {
    vi.spyOn(summariesApi, 'get').mockResolvedValue(null)
    const generate = vi.spyOn(summariesApi, 'generate').mockResolvedValue(makeSummary({ status: 'queued', sections: [] }))
    render(wrap(<SummaryCard doc={doc} />))
    await userEvent.click(await screen.findByRole('button', { name: /Generate summary/ }))
    expect(generate).toHaveBeenCalledWith('doc-1', false)
  })

  it('explains why it can’t summarize when the model isn’t ready', async () => {
    vi.spyOn(summariesApi, 'get').mockResolvedValue(null)
    vi.spyOn(systemApi, 'aiStatus').mockResolvedValue({
      llm: { ready: false, problem: 'Ollama isn’t reachable.', hint: 'ollama pull qwen2.5:3b' },
    } as unknown as AIStatus)
    render(wrap(<SummaryCard doc={doc} />))
    expect(await screen.findByText(/Ollama isn’t reachable/)).toBeInTheDocument()
    expect(screen.getByText('ollama pull qwen2.5:3b')).toBeInTheDocument()
  })

  it('shows the takeaway, sections, “Not reported” and opens cited sources', async () => {
    vi.spyOn(summariesApi, 'get').mockResolvedValue(makeSummary())
    const onOpen = vi.fn()
    render(wrap(<SummaryCard doc={doc} onOpenSource={onOpen} />))
    expect(await screen.findByText('One-line takeaway')).toBeInTheDocument()
    expect(screen.getByText(/Low-rank adapters are cheap and accurate/)).toBeInTheDocument()
    expect(screen.getByText('Not reported')).toBeInTheDocument()
    expect(screen.getByText('Partially supported')).toBeInTheDocument() // problems are spelled out
    expect(screen.getByText(/Written by qwen2.5:3b from 1 passage of this paper in 42 s/)).toBeInTheDocument()

    const problem = screen.getByRole('button', { name: 'Problem' })
    expect(problem).toHaveAttribute('aria-expanded', 'true')
    const [chip] = screen.getAllByRole('button', { name: /Source 1: Low-Rank Adapters, p. 3/ })
    await userEvent.click(chip)
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ number: 1, page_start: 3 }))

    await userEvent.click(problem)
    expect(problem).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(/Full fine-tuning is expensive/)).not.toBeInTheDocument()
  })

  it('regenerates on request', async () => {
    vi.spyOn(summariesApi, 'get').mockResolvedValue(makeSummary())
    const generate = vi.spyOn(summariesApi, 'generate').mockResolvedValue(makeSummary({ id: 's2', status: 'queued', sections: [] }))
    render(wrap(<SummaryCard doc={doc} />))
    await userEvent.click(await screen.findByRole('button', { name: /Regenerate/ }))
    expect(generate).toHaveBeenCalledWith('doc-1', true)
  })

  it('shows progress and the sections written so far', async () => {
    vi.spyOn(summariesApi, 'get').mockResolvedValue(
      makeSummary({
        status: 'running',
        sections: [section('problem', 'Problem', 'Full fine-tuning is expensive [1].')],
        support: null,
        progress: { stage: 'summarizing', detail: 'Reading the method', progress: 0.3 },
      }),
    )
    render(wrap(<SummaryCard doc={doc} />))
    expect(await screen.findByText('Reading the method…')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Summary progress' })).toHaveAttribute('aria-valuenow', '30')
    expect(screen.getByText(/Full fine-tuning is expensive/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Regenerate/ })).not.toBeInTheDocument()
  })

  it('reports a failure with its hint and keeps the previous summary', async () => {
    vi.spyOn(summariesApi, 'get').mockResolvedValue(
      makeSummary({
        id: 's2',
        status: 'failed',
        sections: [],
        support: null,
        error_message: 'Can’t reach Ollama.',
        error_hint: 'Start Ollama',
        previous: makeSummary(),
      }),
    )
    const generate = vi.spyOn(summariesApi, 'generate').mockResolvedValue(makeSummary({ status: 'queued' }))
    render(wrap(<SummaryCard doc={doc} />))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/Can’t reach Ollama/)).toBeInTheDocument()
    expect(within(alert).getByText('Start Ollama')).toBeInTheDocument()
    expect(within(alert).getByText('Showing the previous summary.')).toBeInTheDocument()
    expect(screen.getByText(/Low-rank adapters are cheap and accurate/)).toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(generate).toHaveBeenCalledWith('doc-1', false)
  })

  it('says when a summary is out of date', async () => {
    vi.spyOn(summariesApi, 'get').mockResolvedValue(
      makeSummary({ stale: 'This summary was made from an earlier version of the paper.' }),
    )
    render(wrap(<SummaryCard doc={doc} />))
    expect(await screen.findByText(/earlier version of the paper/)).toBeInTheDocument()
  })
})

describe('summaryMarkdown', () => {
  it('puts the takeaway first and lists only cited sources', () => {
    const text = summaryMarkdown('Low-Rank Adapters', makeSummary())
    expect(text.startsWith('# Summary: Low-Rank Adapters\n\n**One-line takeaway:** Low-rank adapters')).toBe(true)
    expect(text).toContain('## Dataset\nNot reported.')
    expect(text).toContain('Sources:\n[1] Low-Rank Adapters, p. 3 (6 Limitations)')
    expect(text).not.toContain('## One-line takeaway')
  })
})
