/** Research reports: kinds, progress stages, downloads. */
import { BookOpenCheck, Compass, GitFork, Telescope, type LucideIcon } from 'lucide-react'
import type { EvidenceItem, Report, ReportKind } from '@/types/api'

export const REPORT_KINDS: Record<ReportKind, { label: string; icon: LucideIcon; description: string; action: string }> = {
  review: {
    label: 'Literature review',
    icon: BookOpenCheck,
    description: 'A structured review of a topic: themes, chronology, comparison, disagreements and gaps, with citations.',
    action: 'Generate review',
  },
  gaps: {
    label: 'Research gaps',
    icon: Compass,
    description: 'Recurring limitations the authors state, untested combinations and suggested directions — each labelled by where it comes from.',
    action: 'Find gaps',
  },
  disagreements: {
    label: 'Disagreements',
    icon: GitFork,
    description: 'Statements in different papers that may conflict, with the context that could explain them. Never says who is right.',
    action: 'Find disagreements',
  },
  deep_research: {
    label: 'Deep research',
    icon: Telescope,
    description: 'Ask a research question: the assistant plans sub-questions, searches your papers step by step and writes a cited report.',
    action: 'Start research',
  },
}

/** The stages shown while a report is written (job stage → label), in order. */
export const STAGES: Record<ReportKind, { stage: string; label: string }[]> = {
  review: [
    { stage: 'finding', label: 'Finding relevant papers' },
    { stage: 'reading', label: 'Reading the papers' },
    { stage: 'grouping', label: 'Grouping research' },
    { stage: 'analyzing', label: 'Analyzing methodologies' },
    { stage: 'gaps', label: 'Identifying gaps' },
    { stage: 'writing', label: 'Writing the review' },
    { stage: 'verifying', label: 'Verifying citations' },
  ],
  gaps: [
    { stage: 'finding', label: 'Finding the papers' },
    { stage: 'reading', label: 'Reading the papers' },
    { stage: 'disagreements', label: 'Looking for disagreements' },
    { stage: 'gaps', label: 'Identifying gaps' },
    { stage: 'verifying', label: 'Finishing' },
  ],
  disagreements: [
    { stage: 'finding', label: 'Finding the papers' },
    { stage: 'reading', label: 'Reading the papers' },
    { stage: 'disagreements', label: 'Comparing their statements' },
    { stage: 'verifying', label: 'Finishing' },
  ],
  deep_research: [
    { stage: 'planning', label: 'Planning sub-questions' },
    { stage: 'researching', label: 'Searching and answering' },
    { stage: 'writing', label: 'Writing the conclusion' },
  ],
}

export function stageIndex(kind: ReportKind, stage: string | undefined) {
  const order = STAGES[kind]
  const i = order.findIndex((s) => s.stage === stage)
  return i < 0 ? 0 : i
}

/** Sources in the shape the citation chips expect. */
export function asEvidence(report: Pick<Report, 'sources'>): EvidenceItem[] {
  return report.sources.map((s) => ({ ...s, score: s.score ?? 0 }))
}

export const SECTION_DOT: Record<string, string> = {
  supported: 'bg-success',
  partial: 'bg-warning',
  unsupported: 'bg-error',
  insufficient: 'bg-subtle',
  unverified: 'bg-subtle',
}

export const SKIP_REASONS: Record<string, string> = {
  not_ready: 'not processed yet',
  not_indexed: 'not searchable yet',
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function reportFilename(title: string, extension: string) {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'report'
  return `${slug}.${extension}`
}
