import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { chatApi, systemApi } from '@/services/api'
import type { AIStatus, ChatEvent, ChatMessage, Conversation, EvidenceItem } from '@/types/api'
import { ChatPage } from './ChatPage'

const conversation: Conversation = {
  id: 'conv1',
  title: 'How much memory does LoRA save?',
  scope: 'library',
  document_ids: [],
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
  last_message_at: null,
}

const evidence: EvidenceItem[] = [
  {
    number: 1,
    chunk_id: 'c1',
    document: { id: 'd1', title: 'Low-Rank Adapters', year: 2023, authors_display: 'A. Author' },
    section_title: '4 Results',
    page_start: 3,
    page_end: 3,
    char_start: 1200,
    boxes: [[3, 10, 20, 300, 40]],
    quote: 'Low-rank adapters reduce GPU memory by 60 percent compared with full fine-tuning.',
    score: 0.91,
  },
  {
    number: 2,
    chunk_id: 'c2',
    document: { id: 'd2', title: 'Hybrid Retrieval', year: 2024 },
    section_title: '2 Method',
    page_start: 2,
    page_end: 2,
    char_start: 400,
    boxes: [],
    quote: 'BM25 and dense retrieval are fused with reciprocal rank fusion.',
    score: 0.12,
  },
]

const verification = {
  status: 'supported' as const,
  label: 'Well supported',
  explanation: '1 of 1 statement directly supported.',
  verifier: 'cross-encoder/nli-deberta-v3-xsmall',
  claims: [
    { text: 'Adapters reduce GPU memory by 60 percent.', citations: [1], status: 'supported' as const, entailment: 0.97, best_passage: 1 },
  ],
}

const events: ChatEvent[] = [
  { type: 'status', stage: 'understanding', detail: 'Understanding the question' },
  { type: 'status', stage: 'searching', detail: 'Searching your papers' },
  { type: 'evidence', items: evidence, reranker: 'cross-encoder/ms-marco-MiniLM-L-6-v2' },
  { type: 'status', stage: 'writing', detail: 'Writing the answer' },
  { type: 'token', text: 'Adapters reduce **GPU memory** by 60 percent [1]' },
  { type: 'token', text: ' [9].' },
  { type: 'answer', text: 'Adapters reduce **GPU memory** by 60 percent [1].', cited: [1], invalid_citations: [9] },
  { type: 'verification', ...verification },
  { type: 'done', message_id: 'm2', usage: { output_tokens: 12 }, timings_ms: { total: 900 } },
]

const saved: ChatMessage[] = [
  {
    id: 'm1',
    role: 'user',
    content: 'How much memory do adapters save?',
    status: 'complete',
    error: null,
    support: null,
    retrieval_trace: null,
    generation_config: null,
    input_tokens: 0,
    output_tokens: 0,
    latency_ms: null,
    created_at: '2026-10-01T10:00:00Z',
    citations: [],
  },
  {
    id: 'm2',
    role: 'assistant',
    content: 'Adapters reduce **GPU memory** by 60 percent [1].',
    status: 'complete',
    error: null,
    support: verification,
    retrieval_trace: {
      query: {
        intent: 'factual_question',
        intent_cue: null,
        entities: [],
        year_from: null,
        year_to: null,
        temporal_phrase: null,
        follow_up: false,
        retrieval_query: 'How much memory do adapters save?',
        notes: [],
      },
      search: {
        status: 'ok',
        retrievers: ['bm25', 'dense'],
        reranker: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
        searched_papers: 2,
        warnings: [],
        timings_ms: {},
      },
      context: { tokens: 40, decisions: [] },
    },
    generation_config: { llm_model: 'qwen2.5:3b' },
    input_tokens: 300,
    output_tokens: 12,
    latency_ms: 900,
    created_at: '2026-10-01T10:00:01Z',
    citations: evidence.map((e) => ({
      number: e.number,
      chunk_id: e.chunk_id,
      document_id: e.document.id,
      document_title: e.document.title,
      year: e.document.year,
      section_title: e.section_title,
      page_start: e.page_start,
      page_end: e.page_end,
      char_start: e.char_start,
      quote: e.quote,
      boxes: e.boxes,
      score: e.score,
      cited: e.number === 1,
      support_status: e.number === 1 ? 'supported' : null,
    })),
  },
]

const status = (ready: boolean) =>
  ({
    llm: ready
      ? { provider: 'ollama', model: 'qwen2.5:3b', remote: false, ready: true }
      : {
          provider: 'ollama',
          model: 'qwen2.5:3b',
          remote: false,
          ready: false,
          problem: "Ollama isn't reachable at http://localhost:11434.",
          hint: 'Install it from https://ollama.com and start it, then run `ollama pull qwen2.5:3b`.',
        },
  }) as AIStatus

function Location() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname + location.search}</div>
}

function renderAt(url: string, element = <ChatPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route
              path="/chat/:id?"
              element={
                <>
                  {element}
                  <Location />
                </>
              }
            />
            <Route path="/papers/:id" element={<Location />} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.spyOn(systemApi, 'aiStatus').mockResolvedValue(status(true))
  vi.spyOn(chatApi, 'list').mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 })
  Element.prototype.scrollIntoView ??= () => {}
})
afterEach(() => vi.restoreAllMocks())

describe('Research chat', () => {
  it('streams an answer with citations, support status and sources', async () => {
    const create = vi.spyOn(chatApi, 'create').mockResolvedValue(conversation)
    let calls = 0
    vi.spyOn(chatApi, 'get').mockImplementation(async () => ({
      ...conversation,
      // The first fetch (right after creating) is empty; after the answer it's saved.
      messages: calls++ === 0 ? [] : saved,
    }))
    let finish: () => void = () => {}
    const ask = vi.spyOn(chatApi, 'ask').mockImplementation(async (_id, _q, onEvent) => {
      for (const event of events.slice(0, 6)) onEvent(event)
      await new Promise<void>((resolve) => (finish = resolve))
      for (const event of events.slice(6)) onEvent(event)
    })

    renderAt('/chat')
    expect(screen.getByRole('heading', { name: 'Ask your research library' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Your question'), 'How much memory do adapters save?{Enter}')

    // While streaming: the question, the partial answer, a Stop button; an invented [9] is plain text.
    expect(await screen.findByText('How much memory do adapters save?')).toBeInTheDocument()
    expect(await screen.findByText('GPU memory')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop answering' })).toBeInTheDocument()
    expect(screen.getByText(/\[9\]/)).toBeInTheDocument()
    expect(create).toHaveBeenCalledWith({ document_ids: undefined })
    expect(ask.mock.calls[0].slice(0, 2)).toEqual(['conv1', 'How much memory do adapters save?'])
    expect(screen.getByTestId('location')).toHaveTextContent('/chat/conv1')

    finish()
    const support = await screen.findByRole('button', { name: /Well supported/ })
    expect(screen.queryByText(/\[9\]/)).not.toBeInTheDocument()

    // [1] opens the source card with a deep link into the paper.
    await userEvent.click(screen.getByRole('button', { name: /Source 1: Low-Rank Adapters, p\. 3/ }))
    const card = await screen.findByRole('dialog')
    expect(within(card).getByText(/reduce GPU memory by 60 percent/)).toBeInTheDocument()
    expect(within(card).getByText('Relevance 0.91')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: /Open paper/ })).toHaveAttribute(
      'href',
      '/papers/d1?tab=paper&page=3&char=1200',
    )
    await userEvent.keyboard('{Escape}')

    await userEvent.click(support)
    expect(await screen.findByText('1 of 1 statement directly supported.')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')

    await userEvent.click(screen.getByRole('button', { name: /View sources \(2\)/ }))
    const panel = await screen.findByRole('dialog', { name: 'Sources' })
    expect(within(panel).getByText(/2 passages; 1 is cited/)).toBeInTheDocument()
    expect(within(panel).getByText('Hybrid Retrieval')).toBeInTheDocument()
  })

  it('shows a model error with its fix, and the readiness warning', async () => {
    vi.spyOn(systemApi, 'aiStatus').mockResolvedValue(status(false))
    vi.spyOn(chatApi, 'create').mockResolvedValue(conversation)
    vi.spyOn(chatApi, 'get').mockResolvedValue({ ...conversation, messages: [] })
    vi.spyOn(chatApi, 'ask').mockImplementation(async (_id, _q, onEvent) => {
      onEvent({ type: 'evidence', items: evidence, reranker: null })
      onEvent({ type: 'error', message: 'The model “qwen2.5:3b” isn’t installed in Ollama.', hint: 'Run: ollama pull qwen2.5:3b' })
      onEvent({ type: 'done', message_id: 'm2', usage: {}, timings_ms: {} })
    })
    renderAt('/chat')
    expect(await screen.findByText(/The language model isn't ready/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'What limitations do the authors mention?' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('isn’t installed in Ollama')
    expect(alert).toHaveTextContent('Run: ollama pull qwen2.5:3b')
  })

  it('loads a saved conversation and lists retrieval details', async () => {
    vi.spyOn(chatApi, 'list').mockResolvedValue({ items: [conversation], total: 1, limit: 200, offset: 0 })
    vi.spyOn(chatApi, 'get').mockResolvedValue({ ...conversation, messages: saved })
    renderAt('/chat/conv1')
    expect(await screen.findByText('GPU memory')).toBeInTheDocument()
    expect(screen.getAllByText(conversation.title).length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: /View sources/ }))
    const panel = await screen.findByRole('dialog', { name: 'Sources' })
    await userEvent.click(within(panel).getByRole('button', { name: 'How this answer was found' }))
    expect(within(panel).getByText('qwen2.5:3b')).toBeInTheDocument()
    expect(within(panel).getByText('bm25 + dense across 2 papers')).toBeInTheDocument()
  })

  it('in split view, a citation moves the reader instead of leaving the page', async () => {
    vi.spyOn(chatApi, 'get').mockResolvedValue({ ...conversation, messages: saved })
    const onOpen = vi.fn()
    renderAt(
      '/chat/conv1',
      <ChatPanel
        compact
        conversationId="conv1"
        onOpen={onOpen}
        emptyState={{ title: 'Ask', description: '' }}
        suggestions={[]}
      />,
    )
    await userEvent.click(await screen.findByRole('button', { name: /Source 1: Low-Rank Adapters/ }))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ number: 1, page_start: 3 }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/chat/conv1'))
  })

  it('a question right after "New chat" starts a new conversation', async () => {
    // Regression: the conversation came from the URL, which updates in a transition, so a
    // question sent at once went to the previous conversation (and was then cancelled).
    vi.spyOn(chatApi, 'list').mockResolvedValue({ items: [conversation], total: 1, limit: 200, offset: 0 })
    vi.spyOn(chatApi, 'get').mockImplementation(async (id) =>
      id === 'conv1' ? { ...conversation, messages: saved } : { ...conversation, id, messages: [] },
    )
    const create = vi.spyOn(chatApi, 'create').mockResolvedValue({ ...conversation, id: 'conv2' })
    const ask = vi.spyOn(chatApi, 'ask').mockResolvedValue()
    renderAt('/chat/conv1')
    await screen.findByText('GPU memory')
    await userEvent.click(screen.getAllByRole('button', { name: /New chat/ })[0])
    await userEvent.type(screen.getByLabelText('Your question'), 'Which datasets are used?{Enter}')
    await waitFor(() => expect(ask).toHaveBeenCalled())
    expect(create).toHaveBeenCalledTimes(1)
    expect(ask.mock.calls[0][0]).toBe('conv2')
  })
})

describe('Reused answers', () => {
  it('labels an answer reused from a near-identical question and can answer again', async () => {
    const reused = {
      message_id: 'old',
      conversation_id: 'conv0',
      question: 'How much memory do adapters save?',
      asked_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
      similarity: 0.99,
    }
    vi.spyOn(chatApi, 'get').mockResolvedValue({
      ...conversation,
      messages: [saved[0], { ...saved[1], generation_config: { llm_model: 'qwen2.5:3b', reused_from: reused } }],
    })
    const ask = vi.spyOn(chatApi, 'ask').mockResolvedValue(undefined)
    renderAt('/chat/conv1')
    expect(await screen.findByText(/Reused your answer to “How much memory do adapters save\?”/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Answer again/ }))
    await waitFor(() => expect(ask).toHaveBeenCalled())
    const [id, question, , , fresh] = ask.mock.calls[0]
    expect([id, question, fresh]).toEqual(['conv1', 'How much memory do adapters save?', true])
  })
})
