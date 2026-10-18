/** Shared shapes and labels for research chat answers (live or saved). */
import type { LiveTurn } from '@/hooks/useChat'
import type {
  ChatMessage,
  ChatStage,
  EvidenceItem,
  QueryAnalysis,
  RetrievalTraceData,
  ReusedFrom,
  SupportStatus,
  Verification,
} from '@/types/api'

export interface AnswerView {
  text: string
  evidence: EvidenceItem[]
  /** Reranker model whose probabilities the scores are, or null (then scores are only ranks). */
  reranker: string | null
  verification: Verification | null
  state: LiveTurn['state']
  stage: ChatStage | null
  stageDetail: string
  error: { message: string; hint: string | null } | null
  analysis: QueryAnalysis | null
  trace: RetrievalTraceData | null
  model: string | null
  latencyMs: number | null
  tokens: { input: number; output: number } | null
  /** Set when this is an earlier answer reused for a near-identical question. */
  reused: ReusedFrom | null
}

export function fromLive(turn: LiveTurn): AnswerView {
  return {
    text: turn.text,
    evidence: turn.evidence ?? [],
    reranker: turn.reranker,
    verification: turn.verification,
    state: turn.state,
    stage: turn.stage,
    stageDetail: turn.stageDetail,
    error: turn.error,
    analysis: turn.analysis,
    trace: null,
    model: null,
    latencyMs: null,
    tokens: null,
    reused: turn.reused,
  }
}

export function fromSaved(message: ChatMessage): AnswerView {
  const trace = message.retrieval_trace
  return {
    text: message.content,
    evidence: message.citations.map((c) => ({
      number: c.number,
      chunk_id: c.chunk_id,
      document: { id: c.document_id, title: c.document_title, year: c.year },
      section_title: c.section_title,
      page_start: c.page_start,
      page_end: c.page_end,
      char_start: c.char_start,
      boxes: c.boxes,
      quote: c.quote,
      score: c.score,
      cited: c.cited,
      support_status: c.support_status,
    })),
    reranker: trace?.search?.reranker ?? null,
    verification: message.support,
    state: message.status === 'complete' ? 'done' : message.status,
    stage: null,
    stageDetail: '',
    error: message.error ? { message: message.error, hint: null } : null,
    analysis: trace?.query ?? null,
    trace,
    model: (message.generation_config?.llm_model as string | null | undefined) ?? null,
    latencyMs: message.latency_ms,
    tokens:
      message.output_tokens > 0
        ? { input: message.input_tokens, output: message.output_tokens }
        : null,
    reused: (message.generation_config?.reused_from as ReusedFrom | undefined) ?? null,
  }
}

/** Reader deep link for a cited passage; pass `{ boxes }` as router state for exact highlights. */
export function sourceLink(item: EvidenceItem) {
  return `/papers/${item.document.id}?tab=paper&page=${item.page_start}&char=${item.char_start}`
}

export function pagesLabel(item: Pick<EvidenceItem, 'page_start' | 'page_end'>) {
  return item.page_end > item.page_start ? `pp. ${item.page_start}–${item.page_end}` : `p. ${item.page_start}`
}

export const STAGES: { stage: ChatStage; label: string }[] = [
  { stage: 'understanding', label: 'Understanding the question' },
  { stage: 'searching', label: 'Checking papers for context' },
  { stage: 'reading', label: 'Reading the most relevant passages' },
  { stage: 'writing', label: 'Writing the answer' },
  { stage: 'verifying', label: 'Checking each claim against its source' },
]

export const SUPPORT: Record<SupportStatus, { dot: string; tone: 'success' | 'warning' | 'error' | 'neutral' }> = {
  supported: { dot: 'bg-success', tone: 'success' },
  partial: { dot: 'bg-warning', tone: 'warning' },
  unsupported: { dot: 'bg-error', tone: 'error' },
  insufficient: { dot: 'bg-error', tone: 'error' },
  unverified: { dot: 'bg-subtle', tone: 'neutral' },
}

export const CLAIM_STATUS: Record<string, { label: string; dot: string }> = {
  supported: { label: 'Supported', dot: 'bg-success' },
  partial: { label: 'Partly supported', dot: 'bg-warning' },
  unsupported: { label: 'Not supported by the cited passage', dot: 'bg-error' },
  uncited: { label: 'No citation', dot: 'bg-subtle' },
}

export const INTENT_LABELS: Record<string, string> = {
  equation_explanation: 'Equation or notation',
  figure_table_question: 'Figure or table',
  concept_explanation: 'Concept explanation',
  experiment_question: 'Experiments and evaluation',
  factual_question: 'Factual question',
  methodology_question: 'Method question',
  comparison: 'Comparison',
  contradiction_search: 'Looking for disagreements',
  research_gap: 'Research gaps',
  summarization: 'Summary',
  dataset_search: 'Datasets',
  model_search: 'Models',
  timeline: 'Timeline',
  author_search: 'Authors',
  citation_search: 'Citations',
  literature_search: 'Finding papers',
}

export const LIBRARY_SUGGESTIONS = [
  'What methods do my papers use to reduce memory during fine-tuning?',
  'Which datasets are used for evaluation?',
  'What limitations do the authors mention?',
  'Compare the approaches proposed in my papers',
]

export const PAPER_SUGGESTIONS = [
  'Explain the paper in plain language for a new reader.',
  'Walk me through the proposed method step by step.',
  'Explain one key equation and define its symbols.',
  'What do the main figures and tables show?',
  'Which experiments support the main claim?',
  'What assumptions and limitations should I know about?',
  'How could I reproduce the main result?',
]
