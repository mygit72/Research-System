/** Paper summaries: shared helpers. */
import { pagesLabel } from '@/lib/chat'
import type { PaperSummary } from '@/types/api'

/** Everything the summary says, with sources: copy-paste ready (Markdown). */
export function summaryMarkdown(title: string, summary: PaperSummary) {
  const lines = [`# Summary: ${title}`, '']
  const takeaway = summary.sections.find((s) => s.key === 'takeaway')
  if (takeaway && takeaway.status !== 'not_reported') lines.push(`**One-line takeaway:** ${takeaway.text}`, '')
  for (const section of summary.sections) {
    if (section.key === 'takeaway') continue
    lines.push(`## ${section.title}`, section.text, '')
  }
  const cited = new Set(summary.sections.flatMap((s) => s.citations))
  const sources = summary.sources.filter((s) => cited.has(s.number))
  if (sources.length) {
    lines.push('Sources:')
    for (const s of sources)
      lines.push(`[${s.number}] ${s.document.title}, ${pagesLabel(s)}${s.section_title ? ` (${s.section_title})` : ''}`)
  }
  return lines.join('\n').trim()
}
