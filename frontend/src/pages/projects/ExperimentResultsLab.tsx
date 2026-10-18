import { useState } from 'react'
import { BarChart3, FileUp } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useProjectAction } from '@/hooks/useProjects'
import { projectsApi } from '@/services/api'
import type { ExperimentResultsAnalysis, Project } from '@/types/api'
import { PaperRunMatchLab } from './PaperRunMatchLab'

const MAX_FILE_BYTES = 1_000_000

export function ExperimentResultsLab({ project }: { project: Project }) {
  const [file, setFile] = useState<File | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const analyze = useProjectAction(
    project.id,
    (body: { csv_text: string; filename: string }) =>
      projectsApi.analyzeResults(project.id, body.csv_text, body.filename),
    'Results analysis saved to this project',
  )
  const updatedProject = analyze.data ?? project
  const history = updatedProject.steps.experiments.result_analyses ?? []
  const current = history.find((item) => item.id === selectedId) ?? history[0]

  const runAnalysis = async () => {
    if (!file) return
    if (file.size > MAX_FILE_BYTES) {
      toast.error('Choose a CSV smaller than 1 MB.')
      return
    }
    try {
      analyze.mutate({ csv_text: await file.text(), filename: file.name })
      setSelectedId(null)
    } catch (error) {
      toast.error((error as Error).message || 'Could not read that CSV file.')
    }
  }

  return (
    <section aria-labelledby="results-lab-title" className="space-y-4 rounded-xl border border-border bg-surface p-4 sm:p-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <BarChart3 className="size-5" aria-hidden />
        </span>
        <div>
          <p className="text-caption font-medium tracking-wide text-primary uppercase">Run → compare → learn</p>
          <h3 id="results-lab-title" className="mt-1 text-h3 text-text">Experiment results lab</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
            Import <code className="rounded bg-surface-muted px-1">results/results.csv</code> from the generated runner.
            Compare systems on shared seeds, inspect run failures, and see uncertainty around each paired difference.
          </p>
        </div>
      </header>

      <div className="flex flex-col gap-3 rounded-lg bg-surface-muted p-3 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1 text-small font-medium text-text">
          Choose results.csv
          <input
            type="file"
            accept=".csv,text/csv"
            aria-label="Choose results CSV"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-small text-muted file:mr-3 file:rounded-md file:border-0 file:bg-surface file:px-3 file:py-2 file:text-small file:font-medium file:text-text hover:file:bg-primary-soft"
          />
        </label>
        <Button onClick={() => void runAnalysis()} loading={analyze.isPending} disabled={!file || file.size > MAX_FILE_BYTES}>
          <FileUp className="size-4" aria-hidden /> Analyze results
        </Button>
      </div>
      <p className="text-caption leading-relaxed text-muted">
        Supports the CSV exported by this project’s starter runner (up to 1 MB). The app saves the analysis summary;
        it does not keep the uploaded CSV.
        {file && <> Selected: <span className="font-medium text-text">{file.name}</span> · {(file.size / 1024).toFixed(0)} KB.</>}
      </p>

      {history.length > 1 && (
        <label className="flex flex-wrap items-center gap-2 text-small text-muted">
          Saved analyses
          <select
            value={current?.id ?? ''}
            onChange={(event) => setSelectedId(event.target.value || null)}
            className="h-9 max-w-full rounded-md border border-border bg-surface px-2 text-small text-text"
          >
            {history.map((item) => (
              <option key={item.id} value={item.id}>{item.filename} · {new Date(item.created_at).toLocaleString()}</option>
            ))}
          </select>
        </label>
      )}

      {current && <AnalysisResults analysis={current} />}
      <PaperRunMatchLab project={updatedProject} analysis={current ?? null} />
    </section>
  )
}

function AnalysisResults({ analysis }: { analysis: ExperimentResultsAnalysis }) {
  const todo = analysis.status_counts.todo ?? 0
  const errors = analysis.status_counts.error ?? 0
  return (
    <div className="space-y-4 border-t border-border pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-small font-semibold text-text">Analysis · {analysis.filename}</h4>
        <Badge tone="success">Saved</Badge>
        <span className="text-caption text-subtle">{analysis.rows_analyzed} scored rows from {analysis.rows_seen} total</span>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <CountCard label="Scored rows" count={analysis.rows_analyzed} />
        <CountCard label="TODO rows" count={todo} tone={todo ? 'warning' : 'normal'} />
        <CountCard label="Error rows" count={errors} tone={errors ? 'error' : 'normal'} />
      </div>

      <section aria-labelledby="results-comparison-title">
        <div className="mb-2">
          <h5 id="results-comparison-title" className="text-small font-semibold text-text">Paired system comparisons</h5>
          <p className="text-caption text-muted">Δ = system B − system A. Positive means B scored higher; whether that is better depends on the metric.</p>
        </div>
        {analysis.comparisons.length ? (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[820px] border-collapse text-left text-caption">
              <thead className="bg-surface-muted text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Experiment · dataset · metric</th>
                  <th className="px-3 py-2 font-medium">A → B</th>
                  <th className="px-3 py-2 font-medium">Paired seeds</th>
                  <th className="px-3 py-2 font-medium">Δ (B − A)</th>
                  <th className="px-3 py-2 font-medium">95% paired t interval</th>
                </tr>
              </thead>
              <tbody>
                {analysis.comparisons.map((comparison, index) => (
                  <tr key={`${comparison.experiment}-${comparison.dataset}-${comparison.metric}-${comparison.system_a}-${comparison.system_b}-${index}`} className="border-t border-border text-text">
                    <td className="px-3 py-2">{comparison.experiment} · {comparison.dataset} · {comparison.metric}</td>
                    <td className="px-3 py-2">{comparison.system_a} → {comparison.system_b}</td>
                    <td className="px-3 py-2 tabular-nums">{comparison.paired_seed_count}</td>
                    <td className="px-3 py-2 font-mono tabular-nums">{formatMetric(comparison.mean_difference)}</td>
                    <td className="px-3 py-2 font-mono tabular-nums">
                      {comparison.ci95_lower === null || comparison.ci95_upper === null
                        ? 'Need ≥2 shared seeds'
                        : `[${formatMetric(comparison.ci95_lower)}, ${formatMetric(comparison.ci95_upper)}]`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="rounded-md bg-surface-muted p-3 text-small text-muted">No systems had matching seed values in the same experiment, dataset, and metric, so paired comparisons are unavailable.</p>
        )}
      </section>

      <details>
        <summary className="cursor-pointer text-small font-semibold text-text">Per-system summary · {analysis.summaries.length} groups</summary>
        <div className="mt-2 max-h-80 overflow-auto rounded-lg border border-border">
          <table className="w-full min-w-[620px] border-collapse text-left text-caption">
            <thead className="sticky top-0 bg-surface-muted text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Experiment · dataset · metric</th>
                <th className="px-3 py-2 font-medium">System</th>
                <th className="px-3 py-2 font-medium">Seeds</th>
                <th className="px-3 py-2 font-medium">Mean ± SD</th>
              </tr>
            </thead>
            <tbody>
              {analysis.summaries.map((summary, index) => (
                <tr key={`${summary.experiment}-${summary.dataset}-${summary.metric}-${summary.system}-${index}`} className="border-t border-border text-text">
                  <td className="px-3 py-2">{summary.experiment} · {summary.dataset} · {summary.metric}</td>
                  <td className="px-3 py-2">{summary.system}</td>
                  <td className="px-3 py-2 tabular-nums">{summary.seed_count}</td>
                  <td className="px-3 py-2 font-mono tabular-nums">{formatMetric(summary.mean)} ± {formatMetric(summary.std)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      {analysis.issues.length > 0 && (
        <details>
          <summary className="cursor-pointer text-small font-semibold text-text">Rows that need attention · {todo + errors}</summary>
          <ul className="mt-2 max-h-56 space-y-2 overflow-auto rounded-lg bg-surface-muted p-3">
            {analysis.issues.map((issue, index) => (
              <li key={`${issue.row}-${index}`} className="text-caption leading-relaxed text-muted">
                <span className="font-medium text-text">Row {issue.row} · {issue.status} · {issue.system} · {issue.metric}</span>
                {issue.note && <> — {issue.note}</>}
              </li>
            ))}
            {todo + errors > analysis.issues.length && <li className="text-caption text-subtle">Additional issues are included in the counts above.</li>}
          </ul>
        </details>
      )}

      <div className="rounded-md border border-warning/30 bg-warning/5 p-3">
        <p className="text-caption font-medium text-text">Interpret these as research diagnostics</p>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-caption leading-relaxed text-muted">
          {analysis.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
        {analysis.comparisons.some((comparison) => comparison.paired_seed_count < 5) && (
          <p className="mt-2 text-caption font-medium text-warning">At least one comparison has fewer than five paired seeds. Add seeds before drawing strong conclusions.</p>
        )}
      </div>
    </div>
  )
}

function CountCard({ label, count, tone = 'normal' }: { label: string; count: number; tone?: 'normal' | 'warning' | 'error' }) {
  const color = tone === 'error' ? 'text-error' : tone === 'warning' ? 'text-warning' : 'text-text'
  return (
    <div className="rounded-md bg-surface-muted px-3 py-2">
      <p className="text-caption text-muted">{label}</p>
      <p className={`mt-0.5 text-h3 tabular-nums ${color}`}>{count}</p>
    </div>
  )
}

function formatMetric(value: number) {
  return value.toFixed(4)
}
