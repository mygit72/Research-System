import { describe, expect, it } from 'vitest'
import { anchorLink } from '@/lib/organization'
import { paragraphAtPoint, sectionTitles } from '@/lib/reader'
import type { Section } from '@/types/api'

const sections = [
  {
    id: 's1', parent_id: null, level: 1, kind: 'results', title: '5 Results', number: '5', page_start: 2, page_end: 2,
    paragraphs: [
      { text: 'Whole column', kind: 'text', page_start: 2, page_end: 2, char_start: 10, char_end: 20, boxes: [[2, 50, 50, 550, 700]] },
      { text: 'A sentence', kind: 'text', page_start: 2, page_end: 2, char_start: 30, char_end: 40, boxes: [[2, 60, 100, 540, 130]] },
    ],
  },
] as Section[]

describe('passage helpers', () => {
  it('finds the smallest paragraph box under a point, on the right page only', () => {
    expect(paragraphAtPoint(sections, 2, 100, 110)?.char_start).toBe(30)
    expect(paragraphAtPoint(sections, 2, 100, 600)?.char_start).toBe(10)
    expect(paragraphAtPoint(sections, 1, 100, 110)).toBeNull()
    expect(paragraphAtPoint(sections, 2, 5, 5)).toBeNull()
  })

  it('maps paragraphs to their section titles', () => {
    expect(sectionTitles(sections).get(30)).toBe('5 Results')
  })

  it('links notes and bookmarks into the reader', () => {
    expect(anchorLink('d1', { page: 3, char_start: 120 })).toBe('/papers/d1?tab=paper&page=3&char=120')
    expect(anchorLink('d1', { type: 'paper' })).toBe('/papers/d1')
    expect(anchorLink('d1', null)).toBe('/papers/d1')
  })
})
