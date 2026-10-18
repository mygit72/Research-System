import { useMutation, useQuery } from '@tanstack/react-query'
import { Check, Copy, Download, FileCode, Loader2, Pencil, Play, Save, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { SourceCard } from '@/components/chat/Sources'
import { Button } from '@/components/ui/Button'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { useProjectAction } from '@/hooks/useProjects'
import { cn } from '@/lib/cn'
import { asEvidence, reportFilename, saveBlob } from '@/lib/reports'
import { queryClient } from '@/lib/queryClient'
import { projectsApi } from '@/services/api'
import type { CodeSyntaxCheck, Project, ProjectCodeRun } from '@/types/api'
import { ReproducibilityGate } from './ReproducibilityGate'

/** The generated starter project: every file with what it is for, a copy button and a zip. */
export function StarterCodeStep({ project }: { project: Project }) {
  const code = useQuery({
    queryKey: ['projects', 'code', project.id, project.updated_at],
    queryFn: () => projectsApi.code(project.id),
  })
  const draft = useProjectAction(project.id, () => projectsApi.suggest(project.id, 'code'))
  const codeStep = project.steps.code
  const drafts = Object.values(codeStep.drafts)
  const modelDraft = codeStep.drafts.model
  const draftedCount = drafts.filter((d) => d.status === 'drafted').length
  const insufficientDrafts = Object.entries(codeStep.drafts).filter(([, d]) => d.status === 'insufficient')
  const [selected, setSelected] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [editingContent, setEditingContent] = useState<string | null>(null)
  const [syntaxResult, setSyntaxResult] = useState<{
    path: string
    content: string
    result: CodeSyntaxCheck
  } | null>(null)
  const save = useMutation({
    mutationFn: () => projectsApi.saveCodeFile(project.id, file.path, editingContent ?? file.content),
    onSuccess: () => {
      setEditingContent(null)
      void queryClient.invalidateQueries({ queryKey: ['projects', 'code', project.id] })
      toast.success('Saved to this project')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const checkSyntax = useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      projectsApi.checkCodeFile(project.id, path, content),
    onSuccess: (result, input) => setSyntaxResult({ ...input, result }),
    onError: (error: Error) => toast.error(error.message),
  })
  const runCode = useMutation({
    mutationFn: () => projectsApi.runCode(project.id),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['projects', 'code', project.id] })
      toast[result.status === 'succeeded' ? 'success' : 'error'](
        result.status === 'succeeded' ? 'Toy experiment finished' : 'Toy experiment failed',
      )
    },
    onError: (error: Error) => toast.error(error.message),
  })

  if (code.isPending) return <Skeleton className="h-64 w-full" />
  if (code.isError) return <ErrorState error={code.error} onRetry={() => code.refetch()} />
  const files = code.data.files
  const runs = code.data.runs ?? []
  const initialFile = codeStep.status === 'ready' && modelDraft?.status === 'drafted' ? 'model.py' : 'README.md'
  const file = files.find((f) => f.path === (selected ?? initialFile)) ?? files[0]
  const showModelEvidence = file.path === 'model.py' && modelDraft !== undefined
  const modelSources = modelDraft ? asEvidence({ sources: modelDraft.sources }) : []

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(file.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('Copying isn’t available here — select the text instead.')
    }
  }
  const download = async () => {
    try {
      saveBlob(await projectsApi.export(project.id, 'code'), reportFilename(`${project.title} starter code`, 'zip'))
    } catch (error) {
      toast.error((error as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="mb-1">
          <h2 className="text-h2 text-text">Starter code</h2>
          <p className="mt-1 max-w-2xl text-small text-muted">
            A Python workspace generated from your question and idea. Generate a paper-grounded model draft, edit it here,
            and run the configured systems against a small offline dataset. The model module is a learning scaffold; connect it from systems.py before evaluating it.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {codeStep.status === 'running' ? (
            <p className="flex items-center gap-2 text-small text-muted" aria-live="polite">
              <Loader2 className="size-4 animate-spin text-primary" aria-hidden /> Generating a paper-grounded model…
            </p>
          ) : (
            <Button variant="secondary" onClick={() => draft.mutate(undefined)} loading={draft.isPending}>
              <Sparkles className="size-4" aria-hidden /> Generate model code from my papers
            </Button>
          )}
          <Button onClick={download}>
            <Download className="size-4" aria-hidden /> Download .zip
          </Button>
          <Button
            variant="secondary"
            onClick={() => runCode.mutate()}
            loading={runCode.isPending}
            disabled={editingContent !== null || save.isPending}
            title={editingContent !== null ? 'Save this file before running the project' : undefined}
          >
            <Play className="size-4" aria-hidden /> Run toy experiment
          </Button>
        </div>
      </div>
      {codeStep.error && <p className="text-small text-error">{codeStep.error}</p>}
      {codeStep.status === 'ready' && drafts.length > 0 && (
        <div className="rounded-md border border-border bg-surface-muted p-3 text-small text-muted">
          <p className="font-medium text-text">
            {draftedCount} of {drafts.length} code target(s) drafted.
          </p>
          {draftedCount > 0 && (
            <p className="mt-1">
              Model code is tailored to your idea and research question, but is unverified and has not been run. Read and edit it here before using it.
            </p>
          )}
          {modelDraft?.status === 'drafted' && <p className="mt-1">{modelDraft.note}</p>}
          {insufficientDrafts.map(([target, item]) => (
            <p key={target} className="mt-2">
              <span className="font-medium text-text">{target}:</span> {item.note}
            </p>
          ))}
        </div>
      )}
      {codeStep.status === 'ready' && codeStep.note && drafts.length === 0 && (
        <p className="text-small text-muted">{codeStep.note}</p>
      )}
      <ReproducibilityGate project={project} files={files} />
      <section aria-labelledby="project-runs-title" className="space-y-3 rounded-lg border border-border bg-surface p-4">
        <div>
          <h3 id="project-runs-title" className="text-h3 text-text">Server-side experiment runs</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
            Runs the saved systems in a disposable Docker container on the built-in four-example dataset, with one seed,
            no network access, a 40-second limit and 1 GiB of memory. The runner image includes Python, NumPy and
            CPU PyTorch for small models; project requirements are recorded but never installed automatically. This
            button needs the Docker Compose runner. Download the CSV or predictions and bring them into the Results
            Lab or Failure Explorer for further analysis.
          </p>
        </div>
        {runs.length === 0 ? (
          <p className="text-caption text-subtle">No runs yet. Save your code, then run it to check the configured systems.</p>
        ) : (
          <ul className="space-y-3">
            {runs.map((run) => <CodeRunCard key={run.id} run={run} />)}
          </ul>
        )}
      </section>
      <div
        className={cn(
          'grid gap-4 md:grid-cols-[260px_minmax(0,1fr)]',
          showModelEvidence && 'xl:grid-cols-[220px_minmax(0,1fr)_340px]',
        )}
      >
        <ul aria-label="Files" className="space-y-1">
          {files.map((f) => (
            <li key={f.path}>
              <button
                type="button"
                aria-current={f.path === file.path ? 'true' : undefined}
                onClick={() => {
                  setSelected(f.path)
                  setEditingContent(null)
                  setSyntaxResult(null)
                }}
                className={cn(
                  'w-full rounded-md px-3 py-2 text-left transition-colors',
                  f.path === file.path ? 'bg-primary-soft' : 'hover:bg-surface-muted',
                )}
              >
                <span className="flex items-center gap-2 text-small font-medium text-text">
                  <FileCode className="size-3.5 text-subtle" aria-hidden /> {f.path}
                  {f.content.includes('LLM-DRAFTED') && (
                    <span className="rounded-full bg-primary-soft px-1.5 py-0.5 text-caption font-normal text-primary">
                      drafted
                    </span>
                  )}
                </span>
                <span className={cn('mt-0.5 block text-caption', f.path === file.path ? 'text-muted' : 'text-subtle')}>{f.purpose}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="min-w-0 rounded-lg border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-small font-medium text-text">{file.path}</span>
            <div className="flex items-center gap-1">
              {editingContent === null ? (
                <Button variant="ghost" size="sm" onClick={() => setEditingContent(file.content)}>
                  <Pencil className="size-3.5" aria-hidden /> Edit
                </Button>
              ) : (
                <>
                  <Button variant="ghost" size="sm" onClick={() => setEditingContent(null)} disabled={save.isPending}>
                    <X className="size-3.5" aria-hidden /> Cancel
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => save.mutate()} loading={save.isPending}>
                    <Save className="size-3.5" aria-hidden /> Save to project
                  </Button>
                </>
              )}
              {file.path.endsWith('.py') && (
                <Button
                  variant="ghost"
                  size="sm"
                  loading={checkSyntax.isPending}
                  onClick={() => {
                    const content = editingContent ?? file.content
                    setSyntaxResult(null)
                    checkSyntax.mutate({ path: file.path, content })
                  }}
                >
                  Check syntax
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={copy}>
                {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
          </div>
          {editingContent === null ? (
            <pre
              tabIndex={0}
              aria-label={`Contents of ${file.path}`}
              className="max-h-[32rem] overflow-auto p-3 text-caption leading-relaxed text-text"
            >
              <code>{file.content}</code>
            </pre>
          ) : (
            <textarea
              aria-label={`Edit ${file.path}`}
              value={editingContent}
              onChange={(event) => {
                setEditingContent(event.target.value)
                setSyntaxResult(null)
              }}
              spellCheck={false}
              className="min-h-[32rem] w-full resize-y overflow-auto bg-surface p-3 font-mono text-caption leading-relaxed text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          )}
          {syntaxResult?.path === file.path &&
            syntaxResult.content === (editingContent ?? file.content) && (
              <p
                role="status"
                aria-live="polite"
                className={cn(
                  'border-t border-border px-3 py-2 text-small',
                  syntaxResult.result.valid ? 'text-success' : 'text-error',
                )}
              >
                {syntaxResult.result.valid
                  ? syntaxResult.result.message
                  : `${syntaxResult.result.line ? `Line ${syntaxResult.result.line}${syntaxResult.result.column ? `, column ${syntaxResult.result.column}` : ''}: ` : ''}${syntaxResult.result.message}`}
              </p>
            )}
        </div>
        {showModelEvidence && (
          <aside
            aria-labelledby="model-evidence-title"
            className="min-w-0 space-y-4 rounded-lg border border-border bg-surface p-4 md:col-span-2 xl:col-span-1"
          >
            <div>
              <h3 id="model-evidence-title" className="text-h3 text-text">
                Paper evidence for this draft
              </h3>
              <p className="mt-1 text-caption leading-relaxed text-muted">
                These passages were provided to the model while it generated <code>model.py</code>. They show its source
                material; they do not verify that the code is correct.
              </p>
            </div>
            <div className="space-y-2 rounded-md bg-surface-muted p-3">
              <div>
                <p className="text-caption font-medium text-muted">Built for this research question</p>
                <p className="mt-0.5 text-small leading-relaxed text-text">{project.question || project.idea}</p>
              </div>
              {project.hypothesis && (
                <div>
                  <p className="text-caption font-medium text-muted">Hypothesis</p>
                  <p className="mt-0.5 text-small leading-relaxed text-text">{project.hypothesis}</p>
                </div>
              )}
            </div>
            {modelSources.length > 0 ? (
              <div className="max-h-[48rem] space-y-5 overflow-auto pr-1">
                {modelSources.map((source) => (
                  <SourceCard key={`${source.document.id ?? source.document.title}-${source.number}`} item={source} reranker={null} quoteLimit={640} />
                ))}
              </div>
            ) : (
              <p className="text-small text-muted">
                {modelDraft.note || 'No paper passages were available to support this draft.'}
              </p>
            )}
          </aside>
        )}
      </div>
    </div>
  )
}

function CodeRunCard({ run }: { run: ProjectCodeRun }) {
  const downloadResults = () => {
    if (!run.results_csv) return
    saveBlob(
      new Blob([run.results_csv], { type: 'text/csv;charset=utf-8' }),
      reportFilename(`toy experiment ${run.id.slice(0, 8)}`, 'csv'),
    )
  }
  const downloadPredictions = () => {
    if (!run.predictions_jsonl) return
    saveBlob(
      new Blob([run.predictions_jsonl], { type: 'application/x-ndjson;charset=utf-8' }),
      reportFilename(`toy predictions ${run.id.slice(0, 8)}`, 'jsonl'),
    )
  }

  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className={cn('text-small font-medium', run.status === 'succeeded' ? 'text-success' : 'text-error')}>
            {run.status === 'succeeded' ? 'Completed' : run.timed_out ? 'Timed out' : 'Failed'}
            <span className="ml-2 font-normal text-muted">{new Date(run.created_at).toLocaleString()}</span>
          </p>
          <p className="mt-1 text-caption text-subtle">
            {run.dataset} · seed {run.seed} · {run.duration_ms} ms · Python {run.runtime.python}
          </p>
        </div>
        {run.results_csv && !run.results_csv_truncated && (
          <Button size="sm" variant="secondary" onClick={downloadResults}>
            <Download className="size-3.5" aria-hidden /> Download results.csv
          </Button>
        )}
        {run.predictions_jsonl && !run.predictions_jsonl_truncated && (
          <Button size="sm" variant="secondary" onClick={downloadPredictions}>
            <Download className="size-3.5" aria-hidden /> Download predictions.jsonl
          </Button>
        )}
      </div>
      {run.summary && <pre className="mt-3 max-h-64 overflow-auto rounded bg-surface-muted p-3 text-caption leading-relaxed text-text">{run.summary}</pre>}
      {run.stderr && <pre className="mt-2 max-h-40 overflow-auto rounded bg-surface-muted p-3 text-caption leading-relaxed text-error">{run.stderr}</pre>}
      {(run.results_csv_truncated || run.predictions_jsonl_truncated) && (
        <p className="mt-2 text-caption text-muted">A result file exceeded the download limit and was omitted.</p>
      )}
      <details className="mt-2 text-caption text-subtle">
        <summary className="cursor-pointer">Reproducibility record</summary>
        <dl className="mt-2 grid gap-1 sm:grid-cols-[130px_1fr]">
          <dt>Dataset and split</dt><dd>{run.dataset}; {run.split}</dd>
          <dt>Seed</dt><dd>{run.seed}</dd>
          <dt>Saved files</dt><dd className="break-all">SHA-256 {run.file_manifest_sha256}</dd>
          <dt>Runner image</dt><dd className="break-all">{run.runtime.image_digest}</dd>
          <dt>Installed packages</dt><dd className="break-all">{run.runtime.packages.join(', ') || 'None reported'}</dd>
          <dt>Dependencies</dt><dd>{run.runtime.note}</dd>
        </dl>
      </details>
    </li>
  )
}
