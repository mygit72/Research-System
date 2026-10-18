import { useEffect, useState } from 'react'
import { ArrowDownToLine, BookOpenText, GitCompareArrows, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { sourceLink } from '@/lib/chat'
import { reportFilename, saveBlob } from '@/lib/reports'
import { useProject, useProjectAction } from '@/hooks/useProjects'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { projectsApi } from '@/services/api'
import type { EvidenceItem, ExperimentResultsAnalysis, PaperRunMatch, PaperRunMatchRequest, Project } from '@/types/api'

type FormState = {
  evidence_chunk_id: string
  paper_dataset: string
  paper_system: string
  paper_metric: string
  paper_split: string
  run_split: string
  reported_mean: string
  reported_std: string
  tolerance: string
  map_labels: boolean
  mapping_note: string
}

type PaperSource = Omit<EvidenceItem, 'chunk_id' | 'document'> & {
  chunk_id: string
  document: Omit<EvidenceItem['document'], 'id'> & { id: string }
}

const emptyForm: FormState = {
  evidence_chunk_id: '', paper_dataset: '', paper_system: '', paper_metric: '',
  paper_split: '', run_split: '', reported_mean: '', reported_std: '',
  tolerance: '0.02', map_labels: false, mapping_note: '',
}

export function PaperRunMatchLab({ project, analysis }: { project: Project; analysis: ExperimentResultsAnalysis | null }) {
  const [form, setForm] = useState<FormState>(emptyForm)
  const [summaryIndex, setSummaryIndex] = useState('0')
  const [actionProject, setActionProject] = useState<Project | null>(null)
  const latestProject = useProject(project.id)
  const currentProject = actionProject ?? latestProject.data ?? project
  const sources = projectPaperSources(currentProject)
  const save = useProjectAction<PaperRunMatchRequest>(
    project.id,
    (body) => projectsApi.createPaperRunMatch(project.id, body),
    'Paper-to-run comparison saved with its cited passage',
  )
  const remove = useProjectAction<string>(
    project.id,
    (matchId) => projectsApi.deletePaperRunMatch(project.id, matchId),
    'Paper-to-run comparison removed',
  )
  const matches = currentProject.steps.experiments.paper_run_matches ?? []
  const selectedSummary = analysis?.summaries[Number(summaryIndex)] ?? analysis?.summaries[0]

  useEffect(() => setActionProject(null), [project.updated_at])

  const change = (key: keyof FormState, value: string | boolean) => setForm((current) => ({ ...current, [key]: value }))
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!analysis || !selectedSummary) return
    save.mutate({
      result_analysis_id: analysis.id,
      run_experiment: selectedSummary.experiment,
      run_dataset: selectedSummary.dataset,
      run_system: selectedSummary.system,
      run_metric: selectedSummary.metric,
      run_split: form.run_split.trim(),
      evidence_chunk_id: form.evidence_chunk_id,
      paper_dataset: form.paper_dataset.trim(),
      paper_system: form.paper_system.trim(),
      paper_metric: form.paper_metric.trim(),
      paper_split: form.paper_split.trim(),
      reported_mean: Number(form.reported_mean),
      ...(form.reported_std !== '' ? { reported_std: Number(form.reported_std) } : {}),
      tolerance: Number(form.tolerance),
      map_labels: form.map_labels,
      ...(form.mapping_note.trim() ? { mapping_note: form.mapping_note.trim() } : {}),
    }, { onSuccess: setActionProject })
  }

  return (
    <section aria-labelledby="paper-run-match-title" className="space-y-4 rounded-xl border border-border bg-surface p-4 sm:p-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <GitCompareArrows className="size-5" aria-hidden />
        </span>
        <div>
          <p className="text-caption font-medium tracking-wide text-primary uppercase">Published result → your run</p>
          <h3 id="paper-run-match-title" className="mt-1 text-h3 text-text">Paper-to-Run Match</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
            Compare a result reported in a cited paper with a saved run summary. The app checks dataset, system, metric, and split before calling the values comparable.
          </p>
        </div>
      </header>

      {matches.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-small font-semibold text-text">Saved comparisons · {matches.length}</h4>
          {matches.map((match) => (
            <SavedMatch
              key={match.id}
              match={match}
              deleting={remove.isPending}
              onDelete={() => remove.mutate(match.id, { onSuccess: setActionProject })}
            />
          ))}
        </div>
      )}

      {analysis ? (
        <form onSubmit={submit} className="space-y-4 rounded-lg bg-surface-muted p-3 sm:p-4">
          <div>
            <h4 className="text-small font-semibold text-text">Add a published result</h4>
            <p className="mt-1 text-caption leading-relaxed text-muted">
              Transcribe the paper’s reported value and select the passage that supports it. Confirm the split from the runner config; the imported CSV does not record the split.
            </p>
          </div>

          <label className="block text-small font-medium text-text">
            Run summary from {analysis.filename}
            <select
              aria-label="Run summary"
              value={summaryIndex}
              onChange={(event) => setSummaryIndex(event.target.value)}
              required
              className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-small text-text"
            >
              {analysis.summaries.map((summary, index) => (
                <option key={`${summary.experiment}-${summary.dataset}-${summary.system}-${summary.metric}-${index}`} value={String(index)}>
                  {summary.experiment} · {summary.dataset} · {summary.system} · {summary.metric} — {formatMetric(summary.mean)} ± {formatMetric(summary.std)} ({summary.seed_count} seeds)
                </option>
              ))}
            </select>
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <TextField label="Paper dataset" value={form.paper_dataset} onChange={(value) => change('paper_dataset', value)} />
            <TextField label="Paper system or baseline" value={form.paper_system} onChange={(value) => change('paper_system', value)} />
            <TextField label="Paper metric" value={form.paper_metric} onChange={(value) => change('paper_metric', value)} />
            <TextField label="Paper evaluation split" value={form.paper_split} onChange={(value) => change('paper_split', value)} />
            <TextField label="Run evaluation split · check config.json" value={form.run_split} onChange={(value) => change('run_split', value)} />
            <TextField label="Reported mean" value={form.reported_mean} onChange={(value) => change('reported_mean', value)} type="number" step="any" />
            <TextField label="Reported standard deviation · optional" value={form.reported_std} onChange={(value) => change('reported_std', value)} type="number" min="0" step="any" required={false} />
            <TextField label="Allowed absolute difference" value={form.tolerance} onChange={(value) => change('tolerance', value)} type="number" min="0" step="any" />
          </div>

          <label className="block text-small font-medium text-text">
            Cited passage from this project’s papers
            <select
              aria-label="Cited paper passage"
              value={form.evidence_chunk_id}
              onChange={(event) => change('evidence_chunk_id', event.target.value)}
              required
              className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-small text-text"
            >
              <option value="">Choose a saved paper passage</option>
              {sources.map((source) => (
                <option key={source.chunk_id} value={source.chunk_id}>
                  {source.document.title} · {source.section_title || 'Paper passage'} · p. {source.page_start}
                </option>
              ))}
            </select>
          </label>
          {form.evidence_chunk_id && sources.find((source) => source.chunk_id === form.evidence_chunk_id) && (
            <blockquote className="rounded-md border-l-2 border-primary bg-surface px-3 py-2 text-caption leading-relaxed text-muted">
              {sources.find((source) => source.chunk_id === form.evidence_chunk_id)?.quote}
              <p className="mt-1 text-subtle">Check that this passage supports the transcribed table value.</p>
            </blockquote>
          )}

          <div className="space-y-2 rounded-md border border-border bg-surface p-3">
            <label className="flex items-start gap-2 text-small text-text">
              <input
                type="checkbox"
                checked={form.map_labels}
                onChange={(event) => change('map_labels', event.target.checked)}
                className="mt-0.5 accent-[var(--primary)]"
              />
              <span>Some dataset, metric, or system labels differ, but I verified they refer to the same setup.</span>
            </label>
            {form.map_labels && (
              <label className="block text-caption font-medium text-text">
                Explain the label mapping
                <textarea
                  aria-label="Explain the label mapping"
                  value={form.mapping_note}
                  onChange={(event) => change('mapping_note', event.target.value)}
                  minLength={8}
                  required
                  rows={2}
                  className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-small text-text focus:border-primary focus:outline-none"
                />
              </label>
            )}
            <p className="text-caption leading-relaxed text-muted">
              Different evaluation splits are never mapped. Dataset, metric, and system aliases require your explanation and are marked as user-mapped in the saved record.
            </p>
          </div>

          {sources.length === 0 && (
            <p className="text-small text-warning">No saved cited passages are available. Save a relevant source passage in the project before making this comparison.</p>
          )}
          {analysis.summaries.length === 0 && (
            <p className="text-small text-warning">This analysis contains no scored run summaries to compare.</p>
          )}
          {save.error && <p role="alert" className="text-small text-error">{save.error.message}</p>}
          <Button type="submit" loading={save.isPending} disabled={!sources.length || !analysis.summaries.length}>
            Save paper-to-run comparison
          </Button>
        </form>
      ) : (
        <p className="rounded-md bg-surface-muted p-3 text-small text-muted">Import and analyze a results CSV to compare a saved run with a published paper result.</p>
      )}
    </section>
  )
}

function SavedMatch({ match, deleting, onDelete }: { match: PaperRunMatch; deleting: boolean; onDelete: () => void }) {
  const status = match.status === 'within_tolerance'
    ? { label: 'Within tolerance', tone: 'success' as const }
    : match.status === 'diverged'
      ? { label: 'Outside tolerance', tone: 'warning' as const }
      : { label: 'Not comparable', tone: 'error' as const }
  const evidence: EvidenceItem = {
    number: 1,
    chunk_id: match.paper.chunk_id,
    document: { id: match.paper.document_id, title: match.paper.title, year: match.paper.year },
    section_title: match.paper.section_title,
    page_start: match.paper.page_start,
    page_end: match.paper.page_end,
    char_start: match.paper.char_start,
    boxes: match.paper.boxes,
    quote: match.paper.quote,
    score: 0,
  }
  return (
    <article className="space-y-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={status.tone}>{status.label}</Badge>
        {match.alignment === 'user_mapped' && <Badge tone="info">User-mapped labels</Badge>}
        <span className="text-caption text-subtle">{new Date(match.created_at).toLocaleDateString()}</span>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => exportMatch(match)}>
            <ArrowDownToLine className="size-3.5" aria-hidden /> Export
          </Button>
          <Button size="sm" variant="ghost" onClick={onDelete} loading={deleting} aria-label={`Remove comparison with ${match.paper.title}`}>
            <Trash2 className="size-3.5" aria-hidden /> Remove
          </Button>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <ValueCard label={`Paper · ${match.reported.system}`} value={formatMetric(match.reported.mean)} detail={`${match.reported.metric} · ${match.reported.dataset} · ${match.reported.split}${match.reported.std === null ? '' : ` · SD ${formatMetric(match.reported.std)}`}`} />
        <ValueCard label={`Run · ${match.run.system}`} value={`${formatMetric(match.run.mean)} ± ${formatMetric(match.run.std)}`} detail={`${match.run.metric} · ${match.run.dataset} · ${match.run.split} · ${match.run.seed_count} seeds`} />
        <ValueCard label="Run − paper" value={`${match.difference > 0 ? '+' : ''}${formatMetric(match.difference)}`} detail={`Allowed absolute difference: ${formatMetric(match.tolerance)}${match.relative_difference_percent === null ? '' : ` · ${match.relative_difference_percent.toFixed(1)}% relative gap`}`} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-caption">
        <div className="text-muted">{match.run.filename} · {match.run.experiment} · {match.alignment === 'exact' ? 'Labels and split aligned' : match.alignment === 'user_mapped' ? 'Labels user-mapped; split aligned' : alignmentIssue(match)}</div>
        <Link to={sourceLink(evidence)} state={{ boxes: evidence.boxes }} className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
          <BookOpenText className="size-3.5" aria-hidden /> {match.paper.title} · p. {match.paper.page_start}
        </Link>
      </div>
      {match.mapping_note && <p className="rounded-md bg-info-soft p-2 text-caption text-muted">Label mapping: {match.mapping_note}</p>}
      {match.status === 'not_comparable' && (
        <p className="text-caption leading-relaxed text-warning">{!match.split_matches ? `Split mismatch: paper “${match.reported.split}”, run “${match.run.split}”.` : `Label mismatch: ${match.label_mismatches.map((item) => `${item.field} (“${item.paper}” vs “${item.run}”)`).join('; ')}.`} Numeric delta is shown for reference only.</p>
      )}
      <blockquote className="border-l-2 border-border pl-3 text-caption leading-relaxed text-muted">{match.paper.quote}</blockquote>
    </article>
  )
}

function ValueCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-md bg-surface-muted px-3 py-2"><p className="text-caption text-muted">{label}</p><p className="mt-1 text-h3 font-mono tabular-nums text-text">{value}</p><p className="mt-1 text-caption leading-relaxed text-subtle">{detail}</p></div>
}

function TextField({ label, value, onChange, type = 'text', step, min, required = true }: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'number'
  step?: string
  min?: string
  required?: boolean
}) {
  return (
    <label className="block text-small font-medium text-text">
      {label}
      <input
        aria-label={label}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        step={step}
        min={min}
        className="mt-1 h-10 w-full rounded-md border border-border bg-surface px-3 text-small text-text focus:border-primary focus:outline-none"
      />
    </label>
  )
}

function projectPaperSources(project: Project): PaperSource[] {
  const reportSources = [
    ...(project.steps.questions?.sources ?? []),
    ...(project.steps.outline?.sources ?? []),
  ]
  const fromReports: PaperSource[] = reportSources.flatMap((source, index) =>
    source.chunk_id && source.document.id
      ? [{ ...source, chunk_id: source.chunk_id, document: { ...source.document, id: source.document.id }, number: index + 1, score: source.score ?? 0 }]
      : [],
  )
  const fromRuns: PaperSource[] = (project.steps.experiments.claim_runs ?? []).flatMap((run) =>
    run.evidence.map((source, index) => ({
      number: index + 1,
      chunk_id: source.chunk_id,
      document: { id: source.document_id, title: source.title, year: source.year },
      section_title: source.section_title,
      page_start: source.page_start,
      page_end: source.page_end,
      char_start: source.char_start,
      boxes: source.boxes,
      quote: source.quote,
      score: 0,
    })),
  )
  const unique = new Map<string, PaperSource>()
  for (const source of [...fromReports, ...fromRuns]) {
    if (source.chunk_id && source.document.id && !unique.has(source.chunk_id)) unique.set(source.chunk_id, source)
  }
  return [...unique.values()]
}

function alignmentIssue(match: PaperRunMatch) {
  if (!match.split_matches) return 'Split differs'
  return `Labels differ: ${match.label_mismatches.map((item) => item.field).join(', ')}`
}

function exportMatch(match: PaperRunMatch) {
  const status = match.status === 'within_tolerance' ? 'Within tolerance' : match.status === 'diverged' ? 'Outside tolerance' : 'Not comparable'
  const markdown = [
    `# Paper-to-Run Match: ${match.paper.title}`,
    '',
    `**Assessment:** ${status}`,
    '',
    `**Paper:** ${match.paper.title}${match.paper.year ? ` (${match.paper.year})` : ''}, ${match.paper.section_title || 'paper passage'}, page ${match.paper.page_start}.`,
    '',
    `> ${match.paper.quote}`,
    '',
    '## Reported result',
    '',
    `- System: ${match.reported.system}`,
    `- Dataset: ${match.reported.dataset}`,
    `- Metric: ${match.reported.metric}`,
    `- Split: ${match.reported.split}`,
    `- Mean: ${formatMetric(match.reported.mean)}${match.reported.std === null ? '' : ` ± ${formatMetric(match.reported.std)}`}`,
    '',
    '## Reproduced run',
    '',
    `- Source: ${match.run.filename} · ${match.run.experiment}`,
    `- System: ${match.run.system}`,
    `- Dataset: ${match.run.dataset}`,
    `- Metric: ${match.run.metric}`,
    `- Split: ${match.run.split} (entered by the user; the imported CSV does not record it)`,
    `- Mean ± SD: ${formatMetric(match.run.mean)} ± ${formatMetric(match.run.std)} over ${match.run.seed_count} seeds`,
    '',
    `## Difference`,
    '',
    `Run − paper: ${match.difference > 0 ? '+' : ''}${formatMetric(match.difference)}; allowed absolute difference: ${formatMetric(match.tolerance)}.`,
    match.mapping_note ? `Label mapping note: ${match.mapping_note}` : '',
    '',
    'This comparison relies on the entered paper value, selected cited passage, and user-entered run split. It does not independently verify the transcription or run protocol.',
    '',
  ].filter(Boolean).join('\n')
  saveBlob(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }), reportFilename(`paper run match ${match.paper.title}`, 'md'))
}

function formatMetric(value: number) {
  return value.toFixed(4)
}
