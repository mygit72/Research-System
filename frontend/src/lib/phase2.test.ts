import { describe, expect, it } from 'vitest'
import { estimateRemaining, formatBytes, formatDuration } from '@/lib/format'
import { diffMetadata, initialMetadataForm } from '@/lib/metadata'
import { buildToc, paragraphAt, parseMarkdownTable, renderWidth, searchParagraphs } from '@/lib/reader'
import { precheck } from '@/stores/uploads'
import type { DocumentDetail, Paragraph, Section } from '@/types/api'

const para = (text: string, start: number, page = 1): Paragraph => ({
  text,
  kind: 'text',
  page_start: page,
  page_end: page,
  char_start: start,
  char_end: start + text.length,
  boxes: [[page, 10, 20, 100, 40]],
})

const sections: Section[] = [
  { id: 'p', parent_id: null, level: 0, kind: 'preamble', title: '', number: null, page_start: 1, page_end: 1, paragraphs: [para('Title block', 0)] },
  { id: 'a', parent_id: null, level: 1, kind: 'method', title: 'Method', number: '3', page_start: 1, page_end: 2, paragraphs: [para('We use reciprocal rank fusion.', 20), para('Then a reranker.', 60, 2)] },
  { id: 'b', parent_id: 'a', level: 2, kind: 'method', title: 'Loss', number: '3.1', page_start: 2, page_end: 2, paragraphs: [para('A contrastive loss with RANK terms.', 90, 2)] },
]

describe('reader helpers', () => {
  it('searches paragraphs case-insensitively with snippets', () => {
    const hits = searchParagraphs(sections, 'rank')
    expect(hits.map((h) => h.sectionTitle)).toEqual(['Method', 'Method', 'Loss']) // "reranker" matches too
    expect(hits[0].snippet).toContain('reciprocal rank fusion')
    expect(searchParagraphs(sections, 'r')).toEqual([]) // too short
  })

  it('builds a nested table of contents without the preamble', () => {
    const toc = buildToc(sections)
    expect(toc).toHaveLength(1)
    expect(toc[0].section.title).toBe('Method')
    expect(toc[0].children[0].section.title).toBe('Loss')
  })

  it('finds the paragraph for a citation offset', () => {
    expect(paragraphAt(sections, 65)?.text).toBe('Then a reranker.')
    expect(paragraphAt(sections, 10_000)).toBeNull()
  })

  it('parses markdown tables including escaped pipes', () => {
    expect(parseMarkdownTable('| A | B |\n| --- | --- |\n| 1 | x \\| y |')).toEqual([
      ['A', 'B'],
      ['1', 'x | y'],
    ])
    expect(parseMarkdownTable('not a table')).toBeNull()
  })

  it('picks retina-aware render widths', () => {
    expect(renderWidth(700, 1)).toBe(800)
    expect(renderWidth(700, 2)).toBe(1600)
    expect(renderWidth(300, 1)).toBe(480)
  })
})

describe('metadata diff', () => {
  const doc = {
    title: 'Paper',
    metadata: {
      title: 'Paper',
      authors: [{ name: 'Ada Lovelace', affiliation: 'Analytical Engines', email: null }],
      affiliations: [],
      abstract: 'Old',
      year: 2020,
      publication_date: null,
      venue: null,
      doi: null,
      arxiv_id: null,
      keywords: ['a', 'b'],
      research_area: null,
      provenance: {},
      user_corrected_fields: [],
    },
  } as unknown as DocumentDetail

  it('sends only changed fields and keeps known author details', () => {
    const before = initialMetadataForm(doc)
    const after = { ...before, authors: 'Ada Lovelace\nCharles Babbage', year: '2021', venue: '  ' }
    expect(diffMetadata(before, after, doc)).toEqual({
      authors: [
        { name: 'Ada Lovelace', affiliation: 'Analytical Engines', email: null },
        { name: 'Charles Babbage' },
      ],
      year: 2021,
      venue: null,
    })
    expect(diffMetadata(before, before, doc)).toEqual({})
  })
})

describe('uploads and formatting', () => {
  const file = (name: string, size: number) => new File([new Uint8Array(size)], name)

  it('prechecks type, emptiness and size in the browser', () => {
    expect(precheck(file('paper.pdf', 10), 50)).toBeNull()
    expect(precheck(file('notes.MD', 10), 50)).toBeNull()
    expect(precheck(file('virus.exe', 10), 50)).toMatch(/isn't supported/)
    expect(precheck(file('empty.pdf', 0), 50)).toMatch(/empty/)
    expect(precheck(file('big.pdf', 2 * 1024 * 1024), 1)).toMatch(/1 MB limit/)
  })

  it('formats sizes and durations', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(25 * 1024 * 1024)).toBe('25 MB')
    expect(formatDuration(42)).toBe('42s')
    expect(formatDuration(150)).toBe('3 min')
  })

  it('estimates remaining time only with enough signal', () => {
    const now = Date.parse('2026-01-01T00:01:00Z')
    expect(estimateRemaining('2026-01-01T00:00:00Z', 0.5, now)).toBe(60)
    expect(estimateRemaining('2026-01-01T00:00:00Z', 0.01, now)).toBeNull()
    expect(estimateRemaining(null, 0.5, now)).toBeNull()
  })
})
