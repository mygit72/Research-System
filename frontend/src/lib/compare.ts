/** Paper comparison: which papers can be picked, links, and exporting the table. */
import { pagesLabel } from '@/lib/chat'
import type { Comparison, ComparisonKind, DocumentSummary } from '@/types/api'

export const MIN_COMPARE = 2
export const MAX_COMPARE = 5

export const KIND_LABELS: Record<ComparisonKind, string> = {
  papers: 'Papers',
  methodology: 'Methodology',
}

export function compareLink(ids: string[], kind?: ComparisonKind) {
  const params = new URLSearchParams({ papers: ids.join(',') })
  if (kind && kind !== 'papers') params.set('kind', kind)
  return `/compare?${params}`
}

/** Why a paper can't be compared yet, or null. */
export function compareReason(doc: Pick<DocumentSummary, 'status' | 'index_status'>): string | null {
  if (doc.status !== 'ready') return 'Available once the paper is processed'
  if (doc.index_status === 'failed') return 'This paper couldn’t be indexed; retry indexing first'
  if (doc.index_status !== 'indexed') return 'Available once the paper is indexed'
  return null
}

const plain = (text: string) => text.replace(/\s+/g, ' ').trim()
const columnName = (c: Comparison['columns'][number]) => `${c.letter}. ${c.title}${c.year ? ` (${c.year})` : ''}`

function citedSources(comparison: Comparison) {
  const cited = new Set([
    ...comparison.rows.flatMap((r) => r.cells.flatMap((c) => c.citations)),
    ...(comparison.overview?.citations ?? []),
  ])
  return comparison.sources.filter((s) => cited.has(s.number))
}

function sourceLine(s: Comparison['sources'][number]) {
  return `[${s.number}] ${s.letter ? `${s.letter}. ` : ''}${s.document.title}, ${pagesLabel(s)}${s.section_title ? ` (${s.section_title})` : ''}`
}

/** The comparison as a Markdown document (overview, table, sources). */
export function comparisonMarkdown(comparison: Comparison) {
  const cell = (text: string) => plain(text).replace(/\|/g, '\\|')
  const lines = [`# ${comparison.title}`, '']
  if (comparison.overview && comparison.overview.status !== 'not_reported') lines.push(comparison.overview.text, '')
  lines.push(`| | ${comparison.columns.map((c) => cell(columnName(c))).join(' | ')} |`)
  lines.push(`|---|${comparison.columns.map(() => '---').join('|')}|`)
  for (const row of comparison.rows) lines.push(`| **${row.title}** | ${row.cells.map((c) => cell(c.text)).join(' | ')} |`)
  const sources = citedSources(comparison)
  if (sources.length) lines.push('', 'Sources:', ...sources.map(sourceLine))
  return lines.join('\n')
}

/** The table as CSV (RFC 4180 quoting); sources follow in their own rows. */
export function comparisonCsv(comparison: Comparison) {
  const quote = (value: string) => `"${plain(value).replace(/"/g, '""')}"`
  const rows = [
    ['Category', ...comparison.columns.map(columnName)],
    ...comparison.rows.map((row) => [row.title, ...row.cells.map((c) => c.text)]),
  ]
  const sources = citedSources(comparison)
  if (sources.length) rows.push([], ['Sources'], ...sources.map((s) => [sourceLine(s)]))
  return rows.map((row) => row.map(quote).join(',')).join('\r\n')
}

export function download(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = Object.assign(document.createElement('a'), { href: url, download: filename })
  link.click()
  URL.revokeObjectURL(url)
}

export function fileName(title: string, extension: string) {
  const base = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80)
  return `${base || 'comparison'}.${extension}`
}

export const STATUS_LABEL = {
  queued: { label: 'Waiting', tone: 'neutral' },
  running: { label: 'Writing…', tone: 'info' },
  ready: { label: 'Ready', tone: 'success' },
  failed: { label: 'Failed', tone: 'error' },
} as const

/** Row agreement, computed from the cells' words (not judged by the model). */
export const AGREEMENT = {
  similar: { label: 'Similar', dot: 'bg-success', hint: 'The papers describe this in largely the same words.' },
  different: { label: 'Differs', dot: 'bg-warning', hint: 'The papers describe this differently.' },
  partial: { label: 'Not reported by all', dot: 'bg-subtle', hint: 'At least one paper doesn’t report this.' },
  none: { label: 'Not reported', dot: 'bg-border-strong', hint: 'None of the papers report this.' },
} as const
