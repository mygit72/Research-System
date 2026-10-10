import { describe, expect, it } from 'vitest'
import type { SearchHit } from '@/types/api'
import {
  activeFilterCount,
  describeMatch,
  groupByPaper,
  highlightSegments,
  paperLink,
  readSearchState,
  writeSearchState,
} from './search'

describe('search URL state', () => {
  it('round-trips and keeps default values out of the URL', () => {
    const state = readSearchState(
      new URLSearchParams('q=rank+fusion&mode=keyword&from=2020&author=A&author=B&refs=1&debug=1'),
    )
    expect(state).toEqual({
      query: 'rank fusion',
      mode: 'keyword',
      limit: 20,
      rerank: true,
      debug: true,
      filters: { year_from: 2020, authors: ['A', 'B'], include_references: true },
    })
    expect(readSearchState(writeSearchState(state))).toEqual(state)
    expect(writeSearchState({ ...state, mode: 'hybrid', debug: false, filters: {} }).toString()).toBe(
      'q=rank+fusion',
    )
  })

  it('ignores invalid values', () => {
    const state = readSearchState(new URLSearchParams('q=x&mode=magic&limit=7&from=abc'))
    expect(state.mode).toBe('hybrid')
    expect(state.limit).toBe(20)
    expect(state.filters).toEqual({})
    expect(state.rerank).toBe(true)
    expect(readSearchState(new URLSearchParams('rerank=0')).rerank).toBe(false)
    expect(writeSearchState({ ...state, rerank: false }).get('rerank')).toBe('0')
  })

  it('counts active filters', () => {
    expect(activeFilterCount({})).toBe(0)
    expect(activeFilterCount({ year_from: 2020, year_to: 2024, authors: ['a', 'b'] })).toBe(3)
  })
})

describe('highlightSegments', () => {
  const text = 'We fuse rankings with reciprocal rank fusion and rerank.'

  it('marks highlighted spans', () => {
    const segments = highlightSegments(text, [[22, 44]])
    expect(segments.filter((s) => s.mark).map((s) => s.text)).toEqual(['reciprocal rank fusion'])
    expect(segments.map((s) => s.text).join('')).toBe(text)
  })

  it('clips to the snippet range and adds ellipses', () => {
    const segments = highlightSegments(text, [[3, 7], [22, 44]], [8, 44])
    expect(segments[0]).toEqual({ text: '…', mark: false })
    expect(segments.at(-1)).toEqual({ text: '…', mark: false })
    expect(segments.filter((s) => s.mark).map((s) => s.text)).toEqual(['reciprocal rank fusion'])
  })

  it('tolerates overlapping and unsorted spans', () => {
    const segments = highlightSegments('abcdef', [[3, 5], [1, 4]])
    expect(segments.map((s) => s.text).join('')).toBe('abcdef')
    expect(segments.filter((s) => s.mark).map((s) => s.text).join('')).toBe('bcde')
  })
})

const hit = (doc: string, chunk: string, score: number): SearchHit =>
  ({
    chunk_id: chunk,
    document: { id: doc, title: doc, authors_display: '', year: null, doc_type: 'pdf', venue: null },
    score,
    page_start: 3,
    char_start: 120,
  }) as SearchHit

describe('grouping and links', () => {
  it('groups passages by paper in order of their best passage', () => {
    const groups = groupByPaper([hit('a', '1', 3), hit('b', '2', 2), hit('a', '3', 1)])
    expect(groups.map((g) => [g.document.id, g.hits.map((h) => h.chunk_id)])).toEqual([
      ['a', ['1', '3']],
      ['b', ['2']],
    ])
  })

  it('links to the passage in the reader', () => {
    expect(paperLink(hit('a', '1', 1))).toBe('/papers/a?tab=paper&page=3&char=120')
  })

  it('describes which retrievers matched', () => {
    expect(describeMatch(['bm25', 'dense'])).toBe('Matches your words and their meaning')
    expect(describeMatch(['bm25'])).toBe('Matches your words')
    expect(describeMatch(['dense'])).toBe('Matches the meaning')
  })
})
