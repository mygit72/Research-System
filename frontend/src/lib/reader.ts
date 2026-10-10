/** Pure helpers for the document reader (kept out of components so they're testable). */
import type { Paragraph, Section } from '@/types/api'

export type Box = [number, number, number, number, number] // page, x0, y0, x1, y1

export interface SearchHit {
  sectionId: string
  sectionTitle: string
  paragraph: Paragraph
  snippet: string
}

export function searchParagraphs(sections: Section[], query: string, limit = 50): SearchHit[] {
  const needle = query.trim().toLowerCase()
  if (needle.length < 2) return []
  const hits: SearchHit[] = []
  for (const section of sections) {
    for (const paragraph of section.paragraphs) {
      const index = paragraph.text.toLowerCase().indexOf(needle)
      if (index === -1) continue
      const start = Math.max(0, index - 50)
      const end = Math.min(paragraph.text.length, index + needle.length + 70)
      hits.push({
        sectionId: section.id,
        sectionTitle: section.title || 'Front matter',
        paragraph,
        snippet: `${start > 0 ? '…' : ''}${paragraph.text.slice(start, end)}${end < paragraph.text.length ? '…' : ''}`,
      })
      if (hits.length >= limit) return hits
    }
  }
  return hits
}

/** The paragraph containing a global character offset (used by citation deep links). */
export function paragraphAt(sections: Section[], offset: number): Paragraph | null {
  for (const section of sections) {
    for (const paragraph of section.paragraphs) {
      if (paragraph.char_start <= offset && offset < paragraph.char_end) return paragraph
    }
  }
  return null
}

export interface TocNode {
  section: Section
  children: TocNode[]
}

export function buildToc(sections: Section[]): TocNode[] {
  const nodes = new Map<string, TocNode>()
  const roots: TocNode[] = []
  for (const section of sections) {
    if (section.kind === 'preamble') continue
    const node: TocNode = { section, children: [] }
    nodes.set(section.id, node)
    const parent = section.parent_id ? nodes.get(section.parent_id) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  return roots
}

/** Pick a server render width bucket for the displayed width (retina-aware). */
export function renderWidth(cssWidth: number, dpr = 1) {
  const target = cssWidth * Math.min(dpr, 2)
  const buckets = [480, 800, 1200, 1600]
  return buckets.find((b) => b >= target) ?? 1600
}

export function parseMarkdownTable(text: string): string[][] | null {
  const lines = text.split('\n').filter((l) => l.trim().startsWith('|'))
  if (lines.length < 2) return null
  const rows = lines
    .filter((l) => !/^\|\s*-{3}/.test(l.trim()))
    .map((l) =>
      l
        .trim()
        .replace(/^\||\|$/g, '')
        .split(/(?<!\\)\|/)
        .map((c) => c.trim().replace(/\\\|/g, '|')),
    )
  return rows.length >= 2 ? rows : null
}

/** The paragraph drawn at a point of a page (PDF coordinates), smallest box first. */
export function paragraphAtPoint(sections: Section[], page: number, x: number, y: number, pad = 2): Paragraph | null {
  let best: { paragraph: Paragraph; area: number } | null = null
  for (const section of sections)
    for (const paragraph of section.paragraphs)
      for (const [p, x0, y0, x1, y1] of paragraph.boxes) {
        if (p !== page || x < x0 - pad || x > x1 + pad || y < y0 - pad || y > y1 + pad) continue
        const area = (x1 - x0) * (y1 - y0)
        if (!best || area < best.area) best = { paragraph, area }
      }
  return best?.paragraph ?? null
}

/** Section title of every paragraph, by its character offset. */
export function sectionTitles(sections: Section[]): Map<number, string> {
  const titles = new Map<number, string>()
  for (const section of sections)
    for (const paragraph of section.paragraphs) titles.set(paragraph.char_start, section.title)
  return titles
}
