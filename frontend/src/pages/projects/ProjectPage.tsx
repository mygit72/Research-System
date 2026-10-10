import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { ArrowLeft, Check, ChevronDown, Download, ExternalLink, Loader2, Plus, Sparkles, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { citationRenderer } from '@/components/chat/citations'
import { Markdown } from '@/components/chat/Markdown'
import { TypeDot } from '@/components/knowledge/Entities'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { PageContainer } from '@/components/ui/PageHeader'
import { Tooltip } from '@/components/ui/Tooltip'
import { useCollections } from '@/hooks/useOrganization'
import { useProject, useProjectAction } from '@/hooks/useProjects'
import { useReport } from '@/hooks/useReports'
import { buttonClass } from '@/lib/buttonStyles'
import { cn } from '@/lib/cn'
import { asEvidence, reportFilename, saveBlob } from '@/lib/reports'
import { projectsApi } from '@/services/api'
import type {
  EntityType,
  GuideStep,
  Project,
  ProjectExperiment,
  ProjectMethodsChoice,
  ProjectMilestone,
  ProjectStep,
  ProjectUpdate,
} from '@/types/api'
import { StarterCodeStep } from './StarterCode'
import { StepGuidePanel } from './StepGuide'

const STEPS: { key: ProjectStep; label: string; hint: string }[] = [
  { key: 'questions', label: 'Research question', hint: 'From your idea to a question you can answer' },
  { key: 'background', label: 'Background', hint: 'A literature review of the papers you build on' },
  { key: 'gaps', label: 'Gap & hypothesis', hint: 'What’s missing, and what you expect to show' },
  { key: 'methods', label: 'Methods', hint: 'Datasets, baselines and metrics your papers use' },
  { key: 'experiments', label: 'Experiments', hint: 'What to run, and by when' },
  { key: 'outline', label: 'Paper outline', hint: 'A draft structure with citations' },
]

const NAV: { key: GuideStep; label: string; hint: string }[] = [
  ...STEPS,
  { key: 'code', label: 'Starter code', hint: 'Runnable code generated from your plan' },
]

type Save = (body: ProjectUpdate, message?: string) => void

function StepHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-4">
      <h2 className="text-h2 text-text">{title}</h2>
      {children && <p className="mt-1 text-small text-muted">{children}</p>}
    </div>
  )
}

function Running({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-small text-muted" aria-live="polite">
      <Loader2 className="size-4 animate-spin text-primary" aria-hidden /> {label}
    </p>
  )
}

// --- 1. questions ---------------------------------------------------------------------------------

function QuestionsStep({ project, save }: { project: Project; save: Save }) {
  const step = project.steps.questions
  const [question, setQuestion] = useState(project.question)
  const suggest = useProjectAction(project.id, () => projectsApi.suggest(project.id, 'questions'))
  const renderCite = useMemo(() => citationRenderer(asEvidence({ sources: step.sources }), null), [step.sources])
  return (
    <div className="space-y-6">
      <StepHeader title="Research question">
        Start from your idea. Suggested questions are written from passages of your papers and cite them; pick one or
        write your own.
      </StepHeader>
      <Card className="p-4">
        <p className="text-caption font-medium text-subtle">Your idea</p>
        <p className="mt-1 text-small text-text">{project.idea}</p>
      </Card>
      <div>
        {step.status === 'running' ? (
          <Running label="Reading related passages and suggesting questions…" />
        ) : (
          <Button variant="secondary" onClick={() => suggest.mutate(undefined)} loading={suggest.isPending}>
            <Sparkles className="size-4" aria-hidden /> {step.suggestions.length ? 'Suggest again' : 'Suggest questions'}
          </Button>
        )}
        {step.error && <p className="mt-2 text-small text-error">{step.error}</p>}
        {step.note && <p className="mt-2 text-small text-muted">{step.note}</p>}
        {step.status === 'ready' && !step.suggestions.length && !step.note && (
          <p className="mt-2 text-small text-muted">No question could be grounded in your papers; write your own below.</p>
        )}
        {step.suggestions.length > 0 && (
          <ul className="mt-3 space-y-2">
            {step.suggestions.map((s) => (
              <li key={s.text} className="rounded-md border border-border p-3">
                <div className="text-small text-text">
                  <Markdown text={`${s.text} ${s.citations.map((n) => `[${n}]`).join('')}`} renderCite={renderCite} />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="secondary" onClick={() => setQuestion(s.text)}>
                    Use this question
                  </Button>
                  <span className="text-caption text-subtle">
                    {s.status === 'related' ? 'Related passages found by the system: ' : 'Builds on '}
                    {s.papers.join('; ')}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <label className="block">
        <span className="text-small font-medium text-text">Your research question</span>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={2}
          className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-small text-text focus:border-primary focus:outline-none"
        />
      </label>
      <Button onClick={() => save({ question }, 'Question saved')} disabled={!question.trim() || question === project.question}>
        Save question
      </Button>
    </div>
  )
}

// --- 2/3. reports ---------------------------------------------------------------------------------

function ReportStep({ project, step }: { project: Project; step: 'background' | 'gaps' }) {
  const report = project.reports[step]
  const start = useProjectAction(project.id, () => projectsApi.startReport(project.id, step))
  const label = step === 'background' ? 'literature review' : 'research-gaps report'
  if (!report)
    return (
      <div className="space-y-2">
        <Button onClick={() => start.mutate(undefined)} loading={start.isPending}>
          {step === 'background' ? 'Write the literature review' : 'Find research gaps'}
        </Button>
        <p className="text-caption text-subtle">
          Over {project.collection_id ? 'the linked collection' : 'the papers that match your question'}. Papers
          without a summary are summarized first, so this can take a while on a local model.
        </p>
      </div>
    )
  return (
    <div className="flex flex-wrap items-center gap-3">
      {report.status === 'queued' || report.status === 'running' ? (
        <Running label={`Writing the ${label}…`} />
      ) : report.status === 'failed' ? (
        <span className="text-small text-error">The {label} failed: {report.error_message}</span>
      ) : (
        <Badge tone="success">
          <Check className="size-3" aria-hidden /> Ready
        </Badge>
      )}
      <Link to={`/reviews/${report.id}`} className={buttonClass('secondary', 'sm')}>
        <ExternalLink className="size-3.5" aria-hidden /> Open the {label}
      </Link>
      {(report.status === 'ready' || report.status === 'failed') && (
        <Button size="sm" variant="ghost" onClick={() => start.mutate(undefined)} loading={start.isPending}>
          Write it again
        </Button>
      )}
    </div>
  )
}

function GapsStep({ project, save }: { project: Project; save: Save }) {
  const reportId = project.reports.gaps?.status === 'ready' ? project.reports.gaps.id : ''
  const report = useReport(reportId)
  const [chosen, setChosen] = useState(project.steps.gaps.chosen?.id ?? '')
  const [hypothesis, setHypothesis] = useState(project.hypothesis)
  const gaps = reportId ? (report.data?.sections.find((s) => s.kind === 'gaps')?.data?.gaps ?? []) : []
  const pick = gaps.find((g) => g.id === chosen)
  return (
    <div className="space-y-6">
      <StepHeader title="Gap & hypothesis">
        Find the gaps in the papers, pick the one your project addresses, and state what you expect to show. Gaps
        stated by the authors are marked separately from ones the system inferred.
      </StepHeader>
      <ReportStep project={project} step="gaps" />
      {reportId && report.isPending && <Skeleton className="h-24 w-full" />}
      {gaps.length > 0 && (
        <fieldset>
          <legend className="mb-2 text-small font-medium text-text">Which gap does your project address?</legend>
          <ul className="space-y-2">
            {gaps.map((g) => (
              <li key={g.id}>
                <label className={cn('flex gap-3 rounded-md border p-3', chosen === g.id ? 'border-primary bg-primary-soft/40' : 'border-border')}>
                  <input type="radio" name="gap" checked={chosen === g.id} onChange={() => setChosen(g.id)} className="mt-1 accent-[var(--primary)]" />
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-2 text-small font-medium text-text">
                      {g.title}
                      <Badge tone={g.origin === 'Stated by the authors' ? 'success' : 'info'}>{g.origin}</Badge>
                    </span>
                    <span className="mt-0.5 block text-small text-muted">{g.statements[0]?.text ?? g.text}</span>
                    <span className="mt-0.5 block text-caption text-subtle">{g.papers.map((p) => p.title).join('; ')}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}
      <label className="block">
        <span className="text-small font-medium text-text">Your hypothesis</span>
        <textarea
          value={hypothesis}
          onChange={(e) => setHypothesis(e.target.value)}
          rows={2}
          placeholder="e.g. Adapting the generator to its retriever with low-rank adapters raises exact match on SciQA-2400."
          className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-small text-text focus:border-primary focus:outline-none"
        />
      </label>
      <Button
        onClick={() =>
          save(
            {
              hypothesis,
              ...(pick ? { gap: { id: pick.id, title: pick.title, text: pick.statements[0]?.text ?? pick.text, origin: pick.origin } } : {}),
            },
            'Saved',
          )
        }
        disabled={!hypothesis.trim()}
      >
        Save gap & hypothesis
      </Button>
    </div>
  )
}

// --- 4. methods -----------------------------------------------------------------------------------

const PLAN_FIELDS: { key: keyof ProjectMethodsChoice; label: string; from: EntityType[]; help: string }[] = [
  { key: 'methods', label: 'Builds on', from: ['method', 'model'], help: 'Methods or models your approach uses' },
  { key: 'baselines', label: 'Baselines', from: ['model', 'method'], help: 'What you compare against' },
  { key: 'datasets', label: 'Datasets', from: ['dataset'], help: 'Where you evaluate' },
  { key: 'metrics', label: 'Metrics', from: ['metric'], help: 'How you measure' },
]

function MethodsStep({ project, save }: { project: Project; save: Save }) {
  const step = project.steps.methods
  const [chosen, setChosen] = useState<ProjectMethodsChoice>(step.chosen)
  const [custom, setCustom] = useState<Record<string, string>>({})
  const find = useProjectAction(project.id, () => projectsApi.methods(project.id))
  const hasSuggestions = Object.values(step.suggestions).some((list) => list && list.length)
  const toggle = (key: keyof ProjectMethodsChoice, name: string) =>
    setChosen((c) => ({ ...c, [key]: c[key].includes(name) ? c[key].filter((n) => n !== name) : [...c[key], name] }))
  return (
    <div className="space-y-6">
      <StepHeader title="Methods">
        What the papers you build on actually use — counted from your papers, with the papers behind each. Choose what
        your plan uses, or add your own.
      </StepHeader>
      <Button variant="secondary" onClick={() => find.mutate(undefined)} loading={find.isPending}>
        {hasSuggestions ? 'Look again' : 'Find what your papers use'}
      </Button>
      {step.paper_count !== undefined && (
        <p className="text-caption text-subtle">From {step.paper_count} papers.</p>
      )}
      {PLAN_FIELDS.map((field) => {
        const options = field.from.flatMap((type) => (step.suggestions[type] ?? []).map((s) => ({ ...s, type })))
        const extra = chosen[field.key].filter((n) => !options.some((o) => o.name === n))
        return (
          <fieldset key={field.key}>
            <legend className="text-small font-medium text-text">
              {field.label} <span className="font-normal text-caption text-subtle">— {field.help}</span>
            </legend>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {options.map((o) => {
                const on = chosen[field.key].includes(o.name)
                return (
                  <Tooltip key={`${o.type}-${o.entity_id}`} content={`Used by ${o.papers.map((p) => p.title).join('; ')}`}>
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => toggle(field.key, o.name)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-sm border px-2 py-1 text-caption font-medium transition-colors',
                        on ? 'border-primary bg-primary-soft text-primary' : 'border-border bg-surface text-text hover:border-border-strong',
                      )}
                    >
                      <TypeDot type={o.type} /> {o.name}
                      <span className="text-subtle tabular-nums">{o.count}</span>
                    </button>
                  </Tooltip>
                )
              })}
              {extra.map((name) => (
                <Badge key={name} tone="primary">
                  {name}
                  <button type="button" aria-label={`Remove ${name}`} onClick={() => toggle(field.key, name)}>
                    <X className="size-3" aria-hidden />
                  </button>
                </Badge>
              ))}
            </div>
            <form
              className="mt-2 flex max-w-sm gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                const value = (custom[field.key] ?? '').trim()
                if (value && !chosen[field.key].includes(value)) setChosen((c) => ({ ...c, [field.key]: [...c[field.key], value] }))
                setCustom((c) => ({ ...c, [field.key]: '' }))
              }}
            >
              <Input
                aria-label={`Add to ${field.label}`}
                placeholder="Add your own…"
                value={custom[field.key] ?? ''}
                onChange={(e) => setCustom((c) => ({ ...c, [field.key]: e.target.value }))}
              />
              <Button type="submit" variant="ghost" size="icon" aria-label={`Add to ${field.label}`}>
                <Plus className="size-4" aria-hidden />
              </Button>
            </form>
          </fieldset>
        )
      })}
      <Button onClick={() => save({ methods: chosen }, 'Method plan saved')}>Save method plan</Button>
    </div>
  )
}

// --- 5. experiments -------------------------------------------------------------------------------

function ExperimentsStep({ project, save }: { project: Project; save: Save }) {
  const step = project.steps.experiments
  const [items, setItems] = useState<ProjectExperiment[]>(step.items)
  const [milestones, setMilestones] = useState<ProjectMilestone[]>(step.milestones)
  const [deadline, setDeadline] = useState(step.deadline ?? '')
  const plan = useProjectAction(project.id, (body: { deadline?: string; replace?: boolean }) =>
    projectsApi.planExperiments(project.id, body),
  )
  const run = (replace: boolean) =>
    plan.mutate(
      { deadline: deadline || undefined, replace },
      {
        onSuccess: (p) => {
          setItems(p.steps.experiments.items)
          setMilestones(p.steps.experiments.milestones)
        },
      },
    )
  const edit = (i: number, field: keyof ProjectExperiment, value: string) =>
    setItems((list) => list.map((item, j) => (j === i ? { ...item, [field]: value } : item)))
  return (
    <div className="space-y-6">
      <StepHeader title="Experiments">
        A plan built from your method choices: one main comparison per dataset, an ablation and an analysis. Edit
        anything; set a deadline to spread milestones.
      </StepHeader>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-caption font-medium text-muted">
          Deadline
          <input
            type="date"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
            className="h-9 rounded-md border border-border bg-surface px-2 text-small text-text"
          />
        </label>
        <Button variant="secondary" onClick={() => run(items.length > 0)} loading={plan.isPending}>
          {items.length ? 'Re-plan from my choices' : 'Plan experiments'}
        </Button>
      </div>
      {items.length > 0 && (
        <ul className="space-y-3">
          {items.map((item, i) => (
            <li key={item.key}>
              <Card className="space-y-2 p-4">
                <div className="flex items-center gap-2">
                  <Badge>{item.kind}</Badge>
                  <Input aria-label="Experiment title" value={item.title} onChange={(e) => edit(i, 'title', e.target.value)} />
                  <Button variant="ghost" size="icon-sm" aria-label={`Remove ${item.title}`} onClick={() => setItems((l) => l.filter((_, j) => j !== i))}>
                    <Trash2 className="size-4" aria-hidden />
                  </Button>
                </div>
                <Input aria-label="Setup" value={item.setup} onChange={(e) => edit(i, 'setup', e.target.value)} />
                <Input aria-label="Goal" value={item.goal} onChange={(e) => edit(i, 'goal', e.target.value)} />
                <p className="text-caption text-subtle">Metrics: {item.metrics.join(', ')}</p>
                <Input aria-label="Notes" placeholder="Notes (compute, risks…)" value={item.notes} onChange={(e) => edit(i, 'notes', e.target.value)} />
              </Card>
            </li>
          ))}
        </ul>
      )}
      {milestones.length > 0 && (
        <div>
          <h3 className="mb-2 text-small font-semibold text-text">Milestones</h3>
          <ul className="space-y-1.5">
            {milestones.map((m, i) => (
              <li key={m.title} className="flex items-center gap-3 text-small">
                <input
                  type="checkbox"
                  aria-label={`Done: ${m.title}`}
                  checked={m.done}
                  onChange={() => setMilestones((l) => l.map((x, j) => (j === i ? { ...x, done: !x.done } : x)))}
                  className="accent-[var(--primary)]"
                />
                <input
                  type="date"
                  aria-label={`Due date: ${m.title}`}
                  value={m.due}
                  onChange={(e) => setMilestones((l) => l.map((x, j) => (j === i ? { ...x, due: e.target.value } : x)))}
                  className="h-8 rounded-md border border-border bg-surface px-2 text-small text-text"
                />
                <span className={cn('text-text', m.done && 'text-subtle line-through')}>{m.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(items.length > 0 || milestones.length > 0) && (
        <Button onClick={() => save({ experiments: items, milestones }, 'Plan saved')}>Save plan</Button>
      )}
    </div>
  )
}

// --- 6. outline -----------------------------------------------------------------------------------

function OutlineStep({ project, save }: { project: Project; save: Save }) {
  const step = project.steps.outline
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const draft = useProjectAction(project.id, () => projectsApi.suggest(project.id, 'outline'))
  const renderCite = useMemo(() => citationRenderer(asEvidence({ sources: step.sources }), null), [step.sources])
  const download = async (format: 'md' | 'docx' | 'latex') => {
    try {
      saveBlob(await projectsApi.export(project.id, format), reportFilename(project.title, format === 'latex' ? 'zip' : format))
    } catch (error) {
      toast.error((error as Error).message)
    }
  }
  return (
    <div className="space-y-6">
      <StepHeader title="Paper outline">
        The introduction is written from your papers (cited and checked); related work comes from your literature
        review; method and experiments are scaffolds from your own plan — nothing about your results is invented.
      </StepHeader>
      <div className="flex flex-wrap items-center gap-2">
        {step.status === 'running' ? (
          <Running label="Drafting the outline…" />
        ) : (
          <Button variant="secondary" onClick={() => draft.mutate(undefined)} loading={draft.isPending} disabled={!project.question}>
            <Sparkles className="size-4" aria-hidden /> {step.sections.length ? 'Draft again' : 'Draft the outline'}
          </Button>
        )}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <Button variant="secondary">
              <Download className="size-4" aria-hidden /> Export <ChevronDown className="size-3.5" aria-hidden />
            </Button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="start" sideOffset={4} className="z-50 min-w-48 rounded-md border border-border bg-surface-elevated p-1 shadow-lg">
              {(
                [
                  ['md', 'Plan — Markdown'],
                  ['docx', 'Plan — Word'],
                  ['latex', 'Outline — LaTeX + BibTeX (.zip)'],
                ] as const
              ).map(([format, label]) => (
                <DropdownMenu.Item
                  key={format}
                  onSelect={() => void download(format)}
                  className="cursor-pointer rounded-sm px-2 py-1.5 text-small text-text outline-none data-[highlighted]:bg-surface-muted"
                >
                  {label}
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
      {!project.question && <p className="text-small text-muted">Choose a research question first.</p>}
      {step.error && <p className="text-small text-error">{step.error}</p>}
      {step.sections.map((section) => (
        <section key={section.key} aria-labelledby={`outline-${section.key}`}>
          <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
            <h3 id={`outline-${section.key}`} className="text-h3 text-text">
              {section.title}
            </h3>
            <span className="text-caption text-subtle">{section.label}</span>
          </div>
          <textarea
            aria-label={`Text of “${section.title}”`}
            value={drafts[section.key] ?? section.text}
            onChange={(e) => setDrafts((d) => ({ ...d, [section.key]: e.target.value }))}
            rows={Math.min(12, Math.max(3, Math.ceil((drafts[section.key] ?? section.text).length / 100)))}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-small leading-relaxed text-text focus:border-primary focus:outline-none"
          />
          {section.citations.length > 0 && (
            <div className="mt-1 text-small text-muted">
              <Markdown text={`Cites: ${section.citations.map((n) => `[${n}]`).join('')}`} renderCite={renderCite} />
            </div>
          )}
        </section>
      ))}
      {Object.keys(drafts).length > 0 && (
        <Button
          onClick={() => {
            save({ outline: Object.entries(drafts).map(([key, text]) => ({ key, text })) }, 'Outline saved')
            setDrafts({})
          }}
        >
          Save outline
        </Button>
      )}
    </div>
  )
}

// --- page -----------------------------------------------------------------------------------------

export function ProjectPage() {
  const { id = '' } = useParams()
  const project = useProject(id)
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const collections = useCollections()
  const saveAction = useProjectAction(id, (body: ProjectUpdate) => projectsApi.update(id, body))
  const save: Save = (body, message) =>
    saveAction.mutate(body, { onSuccess: () => message && toast.success(message) })
  const current: GuideStep = NAV.find((s) => s.key === params.get('step'))?.key ?? 'questions'

  if (project.isPending)
    return (
      <PageContainer width="wide">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="mt-6 h-96 w-full" />
      </PageContainer>
    )
  if (project.isError)
    return (
      <PageContainer>
        <ErrorState error={project.error} onRetry={() => project.refetch()} />
      </PageContainer>
    )
  const p = project.data
  const done = Object.values(p.completion).filter(Boolean).length
  return (
    <PageContainer width="wide">
      <Link to="/projects" className="inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-3.5" aria-hidden /> Research Projects
      </Link>
      <header className="mt-3 mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-h1 text-balance text-text">{p.title}</h1>
          {p.question && <p className="mt-1 text-body text-muted">{p.question}</p>}
          <p className="mt-1 text-caption text-subtle">
            {done} of {STEPS.length} steps done
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Delete project"
          onClick={() => {
            if (window.confirm('Delete this project? Its reports stay in Reviews & Research.'))
              void projectsApi.remove(p.id).then(() => navigate('/projects'))
          }}
        >
          <Trash2 className="size-4" aria-hidden />
        </Button>
      </header>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[240px_minmax(0,1fr)]">
        <nav aria-label="Project steps" className="min-w-0">
          <ol className="flex gap-2 overflow-x-auto lg:flex-col">
            {NAV.map((s, i) => {
              const finished = s.key !== 'code' && p.completion[s.key]
              return (
              <li key={s.key} className="shrink-0">
                <button
                  type="button"
                  aria-current={current === s.key ? 'step' : undefined}
                  onClick={() => setParams({ step: s.key })}
                  className={cn(
                    'flex w-full items-start gap-3 rounded-md px-3 py-2 text-left transition-colors',
                    current === s.key ? 'bg-primary-soft' : 'hover:bg-surface-muted',
                  )}
                >
                  <span
                    className={cn(
                      'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border text-caption tabular-nums',
                      finished ? 'border-success bg-success text-white' : 'border-border text-subtle',
                    )}
                    aria-label={finished ? 'done' : undefined}
                  >
                    {finished ? <Check className="size-3" aria-hidden /> : i + 1}
                  </span>
                  <span className="min-w-0">
                    <span className={cn('block text-small font-medium', current === s.key ? 'text-primary' : 'text-text')}>{s.label}</span>
                    <span className={cn('hidden text-caption lg:block', current === s.key ? 'text-muted' : 'text-subtle')}>{s.hint}</span>
                  </span>
                </button>
              </li>
              )
            })}
          </ol>
        </nav>
        <div className="min-w-0">
          {p.guidance && (
            <section aria-label="Guidance" className="mb-5 rounded-md border border-border bg-surface-muted p-3 text-small">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-medium text-text">Next:</span>
                <span className="text-muted">{p.guidance.next_step.message}</span>
                {p.guidance.next_step.step && p.guidance.next_step.step !== current && (
                  <button
                    type="button"
                    className="text-primary underline underline-offset-2"
                    onClick={() => setParams({ step: p.guidance?.next_step.step ?? current })}
                  >
                    Go to {STEPS.find((s) => s.key === p.guidance?.next_step.step)?.label}
                  </button>
                )}
              </p>
              {p.guidance.notes.map((note) => (
                <p key={note} className="mt-2 text-muted">
                  {note}
                </p>
              ))}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <label htmlFor="project-collection" className="font-medium text-text">
                  Papers for this project
                </label>
                <select
                  id="project-collection"
                  value={p.collection_id ?? ''}
                  disabled={collections.isPending}
                  onChange={(e) => save({ collection_id: e.target.value || null }, 'Project papers updated.')}
                  className="h-9 max-w-full rounded-md border border-border bg-surface px-2 text-small text-text"
                >
                  <option value="">Papers that match my question</option>
                  {collections.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      Collection: {c.name} ({c.paper_count})
                    </option>
                  ))}
                </select>
              </div>
            </section>
          )}
          <StepGuidePanel projectId={p.id} step={current} version={p.updated_at} />
          {current === 'questions' && <QuestionsStep key={p.updated_at} project={p} save={save} />}
          {current === 'background' && (
            <div className="space-y-4">
              <StepHeader title="Background">
                A literature review of the papers your project builds on — themes, chronology, comparison,
                disagreements and gaps, every statement cited.
              </StepHeader>
              <ReportStep project={p} step="background" />
            </div>
          )}
          {current === 'gaps' && <GapsStep project={p} save={save} />}
          {current === 'methods' && <MethodsStep key={p.updated_at} project={p} save={save} />}
          {current === 'experiments' && <ExperimentsStep key={p.updated_at} project={p} save={save} />}
          {current === 'outline' && <OutlineStep key={p.updated_at} project={p} save={save} />}
          {current === 'code' && <StarterCodeStep project={p} />}
        </div>
      </div>
    </PageContainer>
  )
}
