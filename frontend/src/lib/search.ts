/** Search state ↔ URL, result grouping and highlight rendering (pure, unit-tested). */
import type { SearchFilters, SearchHit, SearchMode } from '@/types/api'

export const SEARCH_MODES: { value: SearchMode; label: string; description: string }[] = [
  {
    value: 'hybrid',
    label: 'Hybrid',
    description: 'Exact words and meaning, combined with reciprocal rank fusion (recommended)',
  },
  { value: 'keyword', label: 'Keyword', description: 'Exact words only (BM25)' },
  { value: 'semantic', label: 'Semantic', description: 'Meaning only (embeddings)' },
]

export const RETRIEVER_LABELS: Record<string, string> = {
  bm25: 'Keyword',
  postgres_fts: 'Keyword',
  dense: 'Meaning',
}

export const SECTION_LABELS: Record<string, string> = {
  preamble: 'Title & authors',
  abstract: 'Abstract',
  introduction: 'Introduction',
  related_work: 'Related work',
  method: 'Method',
  experiments: 'Experiments',
  results: 'Results',
  discussion: 'Discussion',
  limitations: 'Limitations',
  conclusion: 'Conclusion',
  future_work: 'Future work',
  references: 'References',
  acknowledgments: 'Acknowledgments',
  appendix: 'Appendix',
  other: 'Other sections',
}

export const DOC_TYPE_LABELS: Record<string, string> = {
  pdf: 'PDF',
  docx: 'Word',
  html: 'Web page',
  markdown: 'Markdown',
  txt: 'Text',
}

export const LIMITS = [10, 20, 50] as const

export interface SearchState {
  query: string
  mode: SearchMode
  filters: SearchFilters
  limit: number
  /** Reorder results with the cross-encoder reranker (on unless turned off). */
  rerank: boolean
  debug: boolean
}

const int = (value: string | null) => {
  if (!value) return undefined
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : undefined
}

const list = (params: URLSearchParams, key: string) => {
  const values = params.getAll(key).filter(Boolean)
  return values.length ? values : undefined
}

export function readSearchState(params: URLSearchParams): SearchState {
  const mode = params.get('mode') as SearchMode | null
  const limit = int(params.get('limit'))
  const filters: SearchFilters = {
    year_from: int(params.get('from')),
    year_to: int(params.get('to')),
    authors: list(params, 'author'),
    doc_types: list(params, 'type'),
    section_kinds: list(params, 'section'),
    document_ids: list(params, 'paper'),
    collection_ids: list(params, 'collection'),
    tags: list(params, 'tag'),
    include_references: params.get('refs') === '1' || undefined,
  }
  return {
    query: params.get('q') ?? '',
    mode: mode && SEARCH_MODES.some((m) => m.value === mode) ? mode : 'hybrid',
    filters: Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined)),
    limit: limit && (LIMITS as readonly number[]).includes(limit) ? limit : 20,
    rerank: params.get('rerank') !== '0',
    debug: params.get('debug') === '1',
  }
}

/** Only non-default values go into the URL, so links stay short and shareable. */
export function writeSearchState(state: SearchState): URLSearchParams {
  const params = new URLSearchParams()
  if (state.query) params.set('q', state.query)
  if (state.mode !== 'hybrid') params.set('mode', state.mode)
  if (state.limit !== 20) params.set('limit', String(state.limit))
  if (!state.rerank) params.set('rerank', '0')
  if (state.debug) params.set('debug', '1')
  const f = state.filters
  if (f.year_from !== undefined) params.set('from', String(f.year_from))
  if (f.year_to !== undefined) params.set('to', String(f.year_to))
  f.authors?.forEach((a) => params.append('author', a))
  f.doc_types?.forEach((t) => params.append('type', t))
  f.section_kinds?.forEach((s) => params.append('section', s))
  f.document_ids?.forEach((d) => params.append('paper', d))
  f.collection_ids?.forEach((c) => params.append('collection', c))
  f.tags?.forEach((t) => params.append('tag', t))
  if (f.include_references) params.set('refs', '1')
  return params
}

export function activeFilterCount(filters: SearchFilters) {
  return (
    (filters.year_from !== undefined || filters.year_to !== undefined ? 1 : 0) +
    (filters.authors?.length ?? 0) +
    (filters.doc_types?.length ?? 0) +
    (filters.section_kinds?.length ?? 0) +
    (filters.document_ids?.length ?? 0) +
    (filters.collection_ids?.length ?? 0) +
    (filters.tags?.length ?? 0) +
    (filters.include_references ? 1 : 0)
  )
}

export interface PaperGroup {
  document: SearchHit['document']
  hits: SearchHit[] // best first
}

/** Passages grouped by paper, papers ordered by their best passage. */
export function groupByPaper(hits: SearchHit[]): PaperGroup[] {
  const groups = new Map<string, PaperGroup>()
  for (const hit of hits) {
    const group = groups.get(hit.document.id)
    if (group) group.hits.push(hit)
    else groups.set(hit.document.id, { document: hit.document, hits: [hit] })
  }
  return [...groups.values()]
}

export interface Segment {
  text: string
  mark: boolean
}

/**
 * Split `text[range]` into plain and highlighted segments. Highlights are
 * clipped to the range; ellipses mark text cut from either end.
 */
export function highlightSegments(
  text: string,
  highlights: [number, number][],
  range: [number, number] = [0, text.length],
): Segment[] {
  const [start, end] = range
  const segments: Segment[] = []
  let cursor = start
  const push = (from: number, to: number, mark: boolean) => {
    if (to > from) segments.push({ text: text.slice(from, to), mark })
  }
  for (const [s, e] of [...highlights].sort((a, b) => a[0] - b[0])) {
    const from = Math.max(s, cursor)
    const to = Math.min(e, end)
    if (to <= from) continue
    push(cursor, from, false)
    push(from, to, true)
    cursor = to
  }
  push(cursor, end, false)
  if (start > 0) segments.unshift({ text: '…', mark: false })
  if (end < text.length) segments.push({ text: '…', mark: false })
  return segments
}

export function paperLink(hit: SearchHit) {
  return `/papers/${hit.document.id}?tab=paper&page=${hit.page_start}&char=${hit.char_start}`
}

export function describeMatch(matchedBy: string[]) {
  const kinds = [...new Set(matchedBy.map((r) => RETRIEVER_LABELS[r] ?? r))]
  if (kinds.length > 1) return 'Matches your words and their meaning'
  return kinds[0] === 'Keyword' ? 'Matches your words' : 'Matches the meaning'
}
