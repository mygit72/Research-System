import { useState } from 'react'
import { ArrowDown, ArrowRight, BookOpenText, ChartNoAxesCombined, Code2, FlaskConical, GitBranch, Lightbulb, MessageCircleQuestion } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { sourceLink } from '@/lib/chat'
import type { ClaimEvidencePassage, EvidenceItem, Project } from '@/types/api'

type Source = ClaimEvidencePassage | Project['steps']['questions']['sources'][number]
type NodeKey = 'paper-evidence' | 'paper-claim' | 'stress-test' | 'test-findings' | 'research-question' | 'code-drafts' | 'experiment-plan' | 'imported-results'

function sourceKey(source: Source) {
  const doc = 'document' in source ? source.document : { id: source.document_id, title: source.title }
  return `${doc.id ?? doc.title}:${source.page_start}:${source.char_start}:${source.quote.slice(0, 100)}`
}

function toEvidence(source: Source, number: number): EvidenceItem {
  if ('document' in source) {
    return { ...source, number, score: source.score ?? 0 }
  }
  return {
    number,
    chunk_id: source.chunk_id,
    document: { id: source.document_id, title: source.title, year: source.year, authors_display: '' },
    section_title: source.section_title,
    page_start: source.page_start,
    page_end: source.page_end,
    char_start: source.char_start,
    boxes: source.boxes,
    quote: source.quote,
    score: 0,
  }
}

function FlowNode({
  title,
  detail,
  status,
  selected,
  onClick,
}: {
  title: string
  detail: string
  status: 'linked' | 'available' | 'empty'
  selected: boolean
  onClick: () => void
}) {
  const style = status === 'linked'
    ? 'border-primary/40 bg-primary-soft/60'
    : status === 'available'
      ? 'border-info/40 bg-info-soft/50'
      : 'border-border bg-surface'
  const label = status === 'linked' ? 'Saved' : status === 'available' ? 'Ready' : 'Not added'
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`min-h-28 min-w-0 flex-1 rounded-lg border p-3 text-left transition hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${style} ${selected ? 'ring-2 ring-primary' : ''}`}
    >
      <span className="flex items-start justify-between gap-2">
        <span className="text-small font-semibold text-text">{title}</span>
        <span className="shrink-0 text-[10px] font-medium uppercase tracking-wide text-muted">{label}</span>
      </span>
      <span className="mt-2 block text-caption leading-relaxed text-muted">{detail}</span>
    </button>
  )
}

function FlowLane({
  title,
  description,
  nodes,
  selected,
  onSelect,
}: {
  title: string
  description: string
  nodes: { key: NodeKey; title: string; detail: string; status: 'linked' | 'available' | 'empty' }[]
  selected: NodeKey
  onSelect: (key: NodeKey) => void
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <div>
        <h4 className="flex items-center gap-2 text-small font-semibold text-text"><GitBranch className="size-4 text-primary" aria-hidden />{title}</h4>
        <p className="mt-0.5 text-caption text-muted">{description}</p>
      </div>
      <div className="flex flex-col gap-1.5 md:flex-row md:items-stretch md:gap-2">
        {nodes.map((node, index) => (
          <div key={node.key} className="contents">
            <FlowNode {...node} selected={selected === node.key} onClick={() => onSelect(node.key)} />
            {index < nodes.length - 1 && (
              <>
                <ArrowRight className="my-auto hidden size-4 shrink-0 text-subtle md:block" aria-hidden />
                <ArrowDown className="mx-auto size-4 shrink-0 text-subtle md:hidden" aria-hidden />
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

export function ResearchLineageMap({ project }: { project: Project }) {
  const [selected, setSelected] = useState<NodeKey>('test-findings')
  const experiments = project.steps.experiments
  const claimRuns = experiments.claim_runs ?? []
  const resultAnalyses = experiments.result_analyses ?? []
  const predictionAnalyses = experiments.prediction_analyses ?? []
  const drafts = Object.entries(project.steps.code.drafts ?? {})
  const attachedClaimSources = Array.from(new Map(claimRuns.flatMap((run) => run.evidence).map((source) => [sourceKey(source), source])).values())
  const distinctClaims = new Set(claimRuns.map((run) => run.claim)).size
  const allSources = Array.from(new Map([
    ...project.steps.questions.sources,
    ...claimRuns.flatMap((run) => run.evidence),
    ...drafts.flatMap(([, draft]) => draft.sources),
  ].map((source) => [sourceKey(source), source])).values())
  const outputCount = resultAnalyses.length + predictionAnalyses.length
  const latestRun = claimRuns[0]
  const selectedTitle: Record<NodeKey, string> = {
    'paper-evidence': 'Paper evidence attached to tests',
    'paper-claim': 'Claim being tested',
    'stress-test': 'Mechanism stress tests',
    'test-findings': 'Observed findings',
    'research-question': 'Research direction',
    'code-drafts': 'Implementation drafts',
    'experiment-plan': 'Planned experiments',
    'imported-results': 'Imported outputs',
  }

  const claimLane: Parameters<typeof FlowLane>[0]['nodes'] = [
    { key: 'paper-evidence', title: 'Paper evidence', detail: `${attachedClaimSources.length} cited passage${attachedClaimSources.length === 1 ? '' : 's'} attached to saved tests`, status: attachedClaimSources.length ? 'linked' : 'empty' },
    { key: 'paper-claim', title: 'Paper claim(s)', detail: claimRuns.length ? `${distinctClaims} distinct claim${distinctClaims === 1 ? '' : 's'} across ${claimRuns.length} saved run${claimRuns.length === 1 ? '' : 's'}` : 'Save a claim with selected citations in the workbench', status: claimRuns.length ? 'linked' : 'empty' },
    { key: 'stress-test', title: 'Stress test', detail: `${claimRuns.length} saved mechanism run${claimRuns.length === 1 ? '' : 's'}`, status: claimRuns.length ? 'linked' : 'empty' },
    { key: 'test-findings', title: 'Findings', detail: latestRun ? `${latestRun.results.length} tested dimensions · seed ${latestRun.seed}` : 'Results appear after a stress test', status: latestRun ? 'linked' : 'empty' },
  ]
  const projectLane: Parameters<typeof FlowLane>[0]['nodes'] = [
    { key: 'research-question', title: 'Question & hypothesis', detail: project.question.trim() ? (project.hypothesis.trim() ? 'Both saved to this project' : 'Question saved · add a hypothesis') : 'Add a research question to begin', status: project.question.trim() && project.hypothesis.trim() ? 'linked' : project.question.trim() ? 'available' : 'empty' },
    { key: 'code-drafts', title: 'Code', detail: drafts.length ? `${drafts.length} model draft${drafts.length === 1 ? '' : 's'} · ${drafts.reduce((n, [, d]) => n + d.sources.length, 0)} source link${drafts.reduce((n, [, d]) => n + d.sources.length, 0) === 1 ? '' : 's'}` : 'Starter project is available to generate', status: drafts.length ? 'linked' : 'available' },
    { key: 'experiment-plan', title: 'Experiment plan', detail: `${experiments.items.length} planned run${experiments.items.length === 1 ? '' : 's'}`, status: experiments.items.length ? 'linked' : 'empty' },
    { key: 'imported-results', title: 'Imported outputs', detail: `${outputCount} analysis${outputCount === 1 ? '' : 'es'} · CSV results and prediction failures`, status: outputCount ? 'linked' : 'empty' },
  ]

  return (
    <section aria-labelledby="research-lineage-title" className="space-y-4 rounded-xl border border-border bg-surface p-4 sm:p-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <GitBranch className="size-5" aria-hidden />
        </span>
        <div>
          <p className="text-caption font-medium tracking-wide text-primary uppercase">Project provenance · interactive map</p>
          <h3 id="research-lineage-title" className="mt-1 text-h3 text-text">Research lineage map</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
            Follow the saved links from source passages to a test and its findings, alongside your project’s question, code, plan and imported outputs. Select any node to inspect its artifacts.
          </p>
        </div>
      </header>

      <div className="space-y-5 rounded-lg bg-surface-muted p-3 sm:p-4">
        <FlowLane
          title="Paper claim → mechanism test"
          description="The saved stress test carries its own claim, selected citations, assumptions and measured outputs."
          nodes={claimLane}
          selected={selected}
          onSelect={setSelected}
        />
        <div className="border-t border-border" />
        <FlowLane
          title="Your project → implementation → observations"
          description="Project-level artifacts are shown as a separate trail; imported summaries are not silently attributed to a particular paper claim."
          nodes={projectLane}
          selected={selected}
          onSelect={setSelected}
        />
      </div>

      <div aria-live="polite" className="rounded-lg border border-border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-small font-semibold text-text">{selectedTitle[selected]}</h4>
          {selected === 'paper-evidence' && <Badge>{attachedClaimSources.length} passages</Badge>}
          {selected === 'stress-test' && <Badge>{claimRuns.length} runs</Badge>}
          {selected === 'imported-results' && <Badge>{outputCount} analyses</Badge>}
        </div>
        <NodeDetails
          selected={selected}
          project={project}
          sources={allSources}
          claimSources={attachedClaimSources}
          claimRuns={claimRuns}
          drafts={drafts}
          resultAnalyses={resultAnalyses}
          predictionAnalyses={predictionAnalyses}
        />
      </div>
      <p className="text-caption leading-relaxed text-subtle">
        A connection records project provenance; it does not prove a claim. The synthetic attention stress test illustrates one mechanism and is not a reproduction of the paper’s translation results.
      </p>
    </section>
  )
}

function NodeDetails({
  selected,
  project,
  sources,
  claimSources,
  claimRuns,
  drafts,
  resultAnalyses,
  predictionAnalyses,
}: {
  selected: NodeKey
  project: Project
  sources: Source[]
  claimSources: ClaimEvidencePassage[]
  claimRuns: NonNullable<Project['steps']['experiments']['claim_runs']>
  drafts: [string, Project['steps']['code']['drafts'][string]][]
  resultAnalyses: NonNullable<Project['steps']['experiments']['result_analyses']>
  predictionAnalyses: NonNullable<Project['steps']['experiments']['prediction_analyses']>
}) {
  if (selected === 'paper-evidence') {
    return claimSources.length ? (
      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {claimSources.map((source, index) => {
          const item = toEvidence(source, index + 1)
          return (
            <li key={sourceKey(source)} className="rounded-md border border-border bg-surface-muted p-3">
              <p className="text-caption font-semibold text-text">{source.title}{source.year ? ` · ${source.year}` : ''}</p>
              <p className="mt-1 text-caption text-muted">{source.section_title || 'Paper passage'} · p. {source.page_start}</p>
              <p className="mt-2 line-clamp-3 text-small leading-relaxed text-text">{source.quote}</p>
              {item.document.id && <Link className="mt-2 inline-flex items-center gap-1 text-caption font-medium text-primary hover:underline" to={sourceLink(item)} state={{ boxes: item.boxes }}><BookOpenText className="size-3.5" aria-hidden />Open at cited passage</Link>}
            </li>
          )
        })}
      </ul>
    ) : <p className="mt-2 text-small text-muted">No claim-test citations are attached yet. {sources.length ? `${sources.length} other paper source reference(s) exist elsewhere in the project, but they are not linked to a saved test.` : 'Find evidence in the workbench and select the passages before running a test.'}</p>
  }

  if (selected === 'paper-claim') {
    return claimRuns.length ? (
      <ul className="mt-3 space-y-2">
        {claimRuns.slice(0, 5).map((run) => (
          <li key={run.id} className="rounded-md bg-surface-muted p-3">
            <p className="text-small font-medium leading-relaxed text-text">{run.claim}</p>
            <p className="mt-1 text-caption text-muted">{run.evidence.length} citation(s) · {new Date(run.created_at).toLocaleDateString()} · seed {run.seed}</p>
            {run.evidence.length > 0 && <ul className="mt-2 space-y-1">{run.evidence.map((source, index) => {
              const item = toEvidence(source, index + 1)
              return <li key={sourceKey(source)}>{item.document.id ? <Link className="text-caption text-primary hover:underline" to={sourceLink(item)} state={{ boxes: item.boxes }}>{source.title} · p. {source.page_start}</Link> : <span className="text-caption text-muted">{source.title} · p. {source.page_start}</span>}</li>
            })}</ul>}
          </li>
        ))}
      </ul>
    ) : <p className="mt-2 text-small text-muted">No saved claim test yet.</p>
  }

  if (selected === 'stress-test' || selected === 'test-findings') {
    return claimRuns.length ? (
      <ul className="mt-3 space-y-2">
        {claimRuns.slice(0, 5).map((run) => (
          <li key={run.id} className="rounded-md bg-surface-muted p-3">
            <div className="flex flex-wrap items-center gap-2 text-caption text-muted">
              <FlaskConical className="size-3.5 text-primary" aria-hidden />{new Date(run.created_at).toLocaleDateString()} · seed {run.seed} · {run.dimensions.length} dimensions
            </div>
            <p className="mt-1 text-small font-medium text-text">{run.claim}</p>
            <p className="mt-1 text-small text-muted">{run.interpretation}</p>
            <p className="mt-1 text-caption text-subtle">{run.limitation}</p>
          </li>
        ))}
      </ul>
    ) : <p className="mt-2 text-small text-muted">Run a cited claim stress test to record the assumptions, seed and mechanism measurements here.</p>
  }

  if (selected === 'research-question') {
    return <div className="mt-2 grid gap-3 sm:grid-cols-3"><TextDetail icon={<MessageCircleQuestion className="size-4" aria-hidden />} title="Idea" text={project.idea} /><TextDetail icon={<Lightbulb className="size-4" aria-hidden />} title="Question" text={project.question || 'No question saved yet.'} /><TextDetail icon={<Lightbulb className="size-4" aria-hidden />} title="Hypothesis" text={project.hypothesis || 'No hypothesis saved yet.'} /></div>
  }

  if (selected === 'code-drafts') {
    return drafts.length ? <ul className="mt-3 space-y-2">{drafts.map(([name, draft]) => <li key={name} className="rounded-md bg-surface-muted p-3"><p className="flex items-center gap-2 text-small font-medium text-text"><Code2 className="size-4 text-primary" aria-hidden />{name} <Badge tone={draft.status === 'drafted' ? 'warning' : 'neutral'}>{draft.status === 'drafted' ? 'LLM draft · unverified' : 'Needs input'}</Badge></p><p className="mt-1 text-caption text-muted">{draft.sources.length} paper source(s) recorded · {draft.note}</p></li>)}</ul> : <p className="mt-2 text-small text-muted">The generated starter project is available from <Link className="font-medium text-primary hover:underline" to={`/projects/${project.id}?step=code`}>Starter code</Link>. Model drafts appear here with their source links and unverified status.</p>
  }

  if (selected === 'experiment-plan') {
    const planned = project.steps.experiments.items
    return planned.length ? <ul className="mt-3 grid gap-2 sm:grid-cols-2">{planned.map((item) => <li key={item.key} className="rounded-md bg-surface-muted p-3"><p className="text-small font-medium text-text">{item.title}</p><p className="mt-1 text-caption text-muted">{item.kind} · {item.metrics.join(', ') || 'metrics not set'}</p><p className="mt-1 text-caption text-muted">{item.setup}</p></li>)}</ul> : <p className="mt-2 text-small text-muted">No experiment plan has been saved yet.</p>
  }

  if (selected === 'imported-results') {
    return <div className="mt-3 grid gap-2 sm:grid-cols-2">{resultAnalyses.map((analysis) => <article key={analysis.id} className="rounded-md bg-surface-muted p-3"><p className="flex items-center gap-2 text-small font-medium text-text"><ChartNoAxesCombined className="size-4 text-primary" aria-hidden />{analysis.filename}</p><p className="mt-1 text-caption text-muted">{analysis.rows_analyzed} scored rows · {analysis.comparisons.length} paired comparisons</p></article>)}{predictionAnalyses.map((analysis) => <article key={analysis.id} className="rounded-md bg-surface-muted p-3"><p className="flex items-center gap-2 text-small font-medium text-text"><ChartNoAxesCombined className="size-4 text-primary" aria-hidden />{analysis.filename}</p><p className="mt-1 text-caption text-muted">{analysis.metric} · {analysis.example_count} questions · {analysis.hard_case_count} hard cases · {analysis.systems.length} systems</p></article>)}{!resultAnalyses.length && !predictionAnalyses.length && <p className="text-small text-muted">Import a results CSV or prediction JSONL in the panels below to add outcome summaries to the map.</p>}</div>
  }

  return <p className="mt-2 text-small text-muted">{sources.length} distinct paper passages are referenced across question suggestions, claim tests and code drafts. Only the citations attached to each saved claim test appear in its evidence node.</p>
}

function TextDetail({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return <article className="rounded-md bg-surface-muted p-3"><p className="flex items-center gap-2 text-caption font-medium text-muted">{icon}{title}</p><p className="mt-1 text-small leading-relaxed text-text">{text}</p></article>
}
