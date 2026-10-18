import { useState } from 'react'
import { AlertTriangle, SearchCheck } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useProjectAction } from '@/hooks/useProjects'
import { projectsApi } from '@/services/api'
import type { PredictionAnalysis, PredictionHardCase, PredictionPassageSnippet, Project } from '@/types/api'

const MAX_FILE_BYTES = 10_000_000

export function PredictionFailureExplorer({ project }: { project: Project }) {
  const [filename, setFilename] = useState('')
  const [jsonlText, setJsonlText] = useState('')
  const [metrics, setMetrics] = useState<string[]>([])
  const [metric, setMetric] = useState('')
  const [higherIsBetter, setHigherIsBetter] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const analyze = useProjectAction(
    project.id,
    (body: { jsonl_text: string; filename: string; metric: string; higher_is_better: boolean }) =>
      projectsApi.analyzePredictions(project.id, body.jsonl_text, body.filename, body.metric, body.higher_is_better),
    'Failure analysis saved to this project',
  )
  const updatedProject = analyze.data ?? project
  const history = updatedProject.steps.experiments.prediction_analyses ?? []
  const current = history.find((item) => item.id === selectedId) ?? history[0]

  const chooseFile = async (file: File | undefined) => {
    setFilename(file?.name ?? '')
    setJsonlText('')
    setMetrics([])
    setMetric('')
    setSelectedId(null)
    analyze.reset()
    if (!file) return
    if (file.size > MAX_FILE_BYTES) {
      toast.error('Choose a predictions file smaller than 10 MB.')
      return
    }
    try {
      const text = await file.text()
      const available = metricNamesIn(text)
      setJsonlText(text)
      setMetrics(available)
      setMetric(available.includes('exact_match') ? 'exact_match' : (available[0] ?? ''))
    } catch (error) {
      toast.error((error as Error).message || 'Could not read that JSONL file.')
    }
  }

  return (
    <section aria-labelledby="prediction-failure-title" className="space-y-4 rounded-xl border border-border bg-surface p-4 sm:p-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-warning/10 text-warning">
          <SearchCheck className="size-5" aria-hidden />
        </span>
        <div>
          <p className="text-caption font-medium tracking-wide text-primary uppercase">Question → prediction → evidence</p>
          <h3 id="prediction-failure-title" className="mt-1 text-h3 text-text">Per-question failure explorer</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
            Import <code className="rounded bg-surface-muted px-1">predictions_*.jsonl</code> from the generated runner.
            See the hardest questions first, compare systems and seeds, and inspect each answer beside its reference and passages.
          </p>
        </div>
      </header>

      <div className="grid gap-3 rounded-lg bg-surface-muted p-3 lg:grid-cols-[minmax(16rem,1fr)_minmax(12rem,0.65fr)_minmax(12rem,0.65fr)_auto] lg:items-end">
        <label className="min-w-0 text-small font-medium text-text">
          Choose prediction JSONL
          <input
            type="file"
            accept=".jsonl,.ndjson,application/x-ndjson,application/json"
            aria-label="Choose prediction JSONL"
            onChange={(event) => void chooseFile(event.target.files?.[0])}
            className="mt-1 block w-full text-small text-muted file:mr-3 file:rounded-md file:border-0 file:bg-surface file:px-3 file:py-2 file:text-small file:font-medium file:text-text hover:file:bg-primary-soft"
          />
        </label>
        <label className="text-small font-medium text-text">
          Score to inspect
          <select
            value={metric}
            onChange={(event) => setMetric(event.target.value)}
            disabled={!metrics.length}
            className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text disabled:opacity-60"
          >
            {metrics.length ? metrics.map((name) => <option key={name} value={name}>{name}</option>) : <option value="">No per-example scores</option>}
          </select>
        </label>
        <label className="text-small font-medium text-text">
          Better score means
          <select
            value={higherIsBetter ? 'higher' : 'lower'}
            onChange={(event) => setHigherIsBetter(event.target.value === 'higher')}
            className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text"
          >
            <option value="higher">Higher is better</option>
            <option value="lower">Lower is better</option>
          </select>
        </label>
        <Button
          onClick={() => {
            if (!jsonlText || !metric) return
            setSelectedId(null)
            analyze.mutate({ jsonl_text: jsonlText, filename, metric, higher_is_better: higherIsBetter })
          }}
          loading={analyze.isPending}
          disabled={!jsonlText || !metric || analyze.isPending}
        >
          Analyze hard cases
        </Button>
      </div>

      {filename && (
        <p className="text-caption text-muted">
          Selected: <span className="font-medium text-text">{filename}</span> · JSONL scores are read in your browser to populate the metric menu; the server saves only the compact analysis.
        </p>
      )}
      {filename && metrics.length === 0 && (
        <p className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-3 text-small leading-relaxed text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          This file has no per-example metric scores. Download the latest project starter code and rerun the experiment to produce an analyzable export.
        </p>
      )}

      {history.length > 1 && (
        <label className="flex flex-wrap items-center gap-2 text-small text-muted">
          Saved analyses
          <select value={current?.id ?? ''} onChange={(event) => setSelectedId(event.target.value || null)} className="h-9 max-w-full rounded-md border border-border bg-surface px-2 text-small text-text">
            {history.map((item) => <option key={item.id} value={item.id}>{item.filename} · {item.metric} · {new Date(item.created_at).toLocaleString()}</option>)}
          </select>
        </label>
      )}

      {current && <FailureResults analysis={current} />}
    </section>
  )
}

function FailureResults({ analysis }: { analysis: PredictionAnalysis }) {
  return (
    <div className="space-y-4 border-t border-border pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-small font-semibold text-text">Hard cases · {analysis.metric}</h4>
        <Badge tone="success">Saved</Badge>
        <span className="text-caption text-subtle">{analysis.records_scored} scored predictions · {analysis.example_count} questions · {analysis.filename}</span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {analysis.summaries.map((summary) => (
          <div key={summary.system} className="rounded-md bg-surface-muted p-3">
            <p className="truncate text-caption font-medium text-muted" title={summary.system}>{summary.system}</p>
            <p className="mt-1 text-h3 tabular-nums text-text">{summary.mean_score.toFixed(3)}</p>
            <p className="text-caption text-subtle">mean across {summary.scored_predictions} scored predictions</p>
          </div>
        ))}
        {analysis.records_without_metric > 0 && (
          <div className="rounded-md bg-warning/5 p-3">
            <p className="text-caption font-medium text-warning">Unscored predictions</p>
            <p className="mt-1 text-h3 tabular-nums text-warning">{analysis.records_without_metric}</p>
          </div>
        )}
      </div>

      <div className="space-y-3">
        <div>
          <h5 className="text-small font-semibold text-text">Hardest questions first</h5>
          <p className="text-caption text-muted">Ranked by the strongest system’s mean {analysis.metric} score; the score direction you selected is {analysis.higher_is_better ? 'higher' : 'lower'} is better.</p>
        </div>
        {analysis.cases.map((item) => <FailureCase key={`${item.experiment}-${item.dataset}-${item.example_id}`} item={item} metric={analysis.metric} />)}
        {analysis.hard_case_count < analysis.example_count && (
          <p className="text-caption text-subtle">Showing the {analysis.hard_case_count} hardest of {analysis.example_count} questions.</p>
        )}
      </div>

      <ul className="list-disc space-y-1 pl-5 text-caption leading-relaxed text-muted">
        {analysis.notes.map((note) => <li key={note}>{note}</li>)}
      </ul>
    </div>
  )
}

function FailureCase({ item, metric }: { item: PredictionHardCase; metric: string }) {
  return (
    <article className="space-y-3 rounded-lg border border-border p-3 sm:p-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-caption text-subtle">{item.experiment} · {item.dataset} · example {item.example_id}</p>
          <h6 className="mt-1 text-small font-semibold leading-relaxed text-text">{item.question}</h6>
        </div>
        <span className="shrink-0 rounded bg-surface-muted px-2 py-1 font-mono text-caption tabular-nums text-muted">
          {metric} spread {item.score_spread === null ? '—' : item.score_spread.toFixed(3)}
        </span>
      </header>

      {item.reference_answers.length > 0 && (
        <div className="rounded-md bg-primary-soft/40 p-3">
          <p className="text-caption font-semibold text-text">Reference answer{item.reference_answers.length > 1 ? 's' : ''}</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-small leading-relaxed text-text">
            {item.reference_answers.map((answer, index) => <li key={`${answer}-${index}`}>{answer}</li>)}
          </ul>
        </div>
      )}

      {item.reference_passages.length > 0 && <PassageList title="Reference passages" passages={item.reference_passages} />}

      <div className="grid gap-3 xl:grid-cols-2">
        {item.systems.map((system) => (
          <section key={system.system} className="min-w-0 rounded-md bg-surface-muted p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h6 className="text-small font-semibold text-text">{system.system}</h6>
              <span className="text-caption tabular-nums text-muted">
                {system.mean_score === null ? 'No score' : `${metric} ${system.mean_score.toFixed(3)}`} · {system.scored_seeds}/{system.run_count} scored runs
              </span>
            </div>
            <div className="mt-2 space-y-3">
              {system.runs.map((run, index) => (
                <div key={`${run.seed}-${index}`} className="border-t border-border/70 pt-2">
                  <p className="text-caption font-medium text-muted">Seed {run.seed} · {run.score === null ? 'unscored' : `${metric} ${run.score.toFixed(3)}`}</p>
                  <p className="mt-1 whitespace-pre-wrap text-small leading-relaxed text-text">{run.answer || 'No answer was logged for this prediction.'}</p>
                  {run.used_passages.length > 0 && <PassageList title="Passages used" passages={run.used_passages} />}
                  {run.retrieved_passages.length > 0 && <PassageList title="Top retrieved passages" passages={run.retrieved_passages} />}
                </div>
              ))}
              {system.run_count > system.runs.length && <p className="text-caption text-subtle">Showing {system.runs.length} of {system.run_count} seed runs.</p>}
            </div>
          </section>
        ))}
      </div>
    </article>
  )
}

function PassageList({ title, passages }: { title: string; passages: PredictionPassageSnippet[] }) {
  return (
    <details className="mt-2 rounded border border-border/70 bg-surface p-2">
      <summary className="cursor-pointer text-caption font-medium text-muted">{title} · {passages.length}</summary>
      <ul className="mt-2 space-y-2">
        {passages.map((passage, index) => (
          <li key={`${passage.index}-${index}`} className="text-caption leading-relaxed text-text">
            <span className="font-mono text-subtle">[{passage.index}]</span>{passage.relevant !== undefined && <span className="ml-1 text-subtle">{passage.relevant ? 'relevant' : 'not labeled relevant'}</span>}
            <p className="mt-0.5">{passage.text}</p>
          </li>
        ))}
      </ul>
    </details>
  )
}

function metricNamesIn(text: string): string[] {
  const names = new Set<string>()
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue
    try {
      const row: unknown = JSON.parse(line)
      if (!row || typeof row !== 'object' || !('metric_scores' in row)) continue
      const scores = (row as { metric_scores?: unknown }).metric_scores
      if (scores && typeof scores === 'object' && !Array.isArray(scores)) {
        Object.keys(scores).forEach((name) => names.add(name))
      }
    } catch {
      // The backend reports malformed line numbers with a clearer validation message.
    }
  }
  return [...names].sort((a, b) => a.localeCompare(b))
}
