import { useMutation } from '@tanstack/react-query'
import { Check, FlaskConical, Search, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { SourceCard } from '@/components/chat/Sources'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Field } from '@/components/ui/Input'
import { useProjectAction } from '@/hooks/useProjects'
import { projectsApi } from '@/services/api'
import type { ClaimEvidencePassage, ClaimEvidenceSearch, ClaimStressTestRun, EvidenceItem, Project } from '@/types/api'

const DIMENSION_CHOICES = [4, 16, 64, 128, 256]
const TRANSFORMER_CLAIM =
  'Scaling dot-product attention by √dₖ keeps softmax away from saturated regions as the key dimension grows.'

function toEvidenceItem(source: ClaimEvidencePassage, number: number): EvidenceItem {
  return {
    number,
    chunk_id: source.chunk_id,
    document: {
      id: source.document_id,
      title: source.title,
      year: source.year,
      authors_display: '',
    },
    section_title: source.section_title,
    page_start: source.page_start,
    page_end: source.page_end,
    char_start: source.char_start,
    boxes: source.boxes,
    quote: source.quote,
    score: 0,
  }
}

export function ClaimExperimentWorkbench({ project }: { project: Project }) {
  const [claim, setClaim] = useState('')
  const [evidenceSearch, setEvidenceSearch] = useState<ClaimEvidenceSearch | null>(null)
  const [selectedEvidence, setSelectedEvidence] = useState<string[]>([])
  const [dimensions, setDimensions] = useState<number[]>([4, 16, 64, 256])
  const [seed, setSeed] = useState('42')
  const [viewRunId, setViewRunId] = useState<string | null>(null)
  const findEvidence = useMutation({
    mutationFn: () => projectsApi.findClaimEvidence(project.id, claim.trim()),
    onSuccess: (result) => {
      setEvidenceSearch(result)
      setSelectedEvidence(result.passages[0] ? [result.passages[0].chunk_id] : [])
      if (!result.passages.length) toast.message('No matching passages found in this project’s papers.')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const runAction = useProjectAction(
    project.id,
    (body: { claim: string; evidence_chunk_ids: string[]; dimensions: number[]; seed: number }) =>
      projectsApi.runClaimStressTest(project.id, body),
    'Claim stress test saved to this project',
  )
  const resultProject = runAction.data ?? project
  const runs = resultProject.steps.experiments.claim_runs ?? []
  const displayedRun = runs.find((run) => run.id === viewRunId) ?? runs[0]
  const parsedSeed = Number(seed)
  const canRun =
    claim.trim().length >= 12 &&
    selectedEvidence.length > 0 &&
    dimensions.length >= 2 &&
    Number.isInteger(parsedSeed) &&
    parsedSeed >= 0 &&
    parsedSeed <= 2_147_483_647

  const search = () => {
    setEvidenceSearch(null)
    setSelectedEvidence([])
    findEvidence.mutate()
  }
  const toggleDimension = (dimension: number) => {
    setDimensions((current) =>
      current.includes(dimension)
        ? current.filter((item) => item !== dimension)
        : current.length < 5
          ? [...current, dimension].sort((a, b) => a - b)
          : current,
    )
  }
  const toggleEvidence = (id: string) => {
    setSelectedEvidence((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : current.length < 5 ? [...current, id] : current,
    )
  }

  return (
    <section aria-labelledby="claim-workbench-title" className="space-y-5 rounded-xl border border-border bg-surface p-4 sm:p-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <FlaskConical className="size-5" aria-hidden />
        </span>
        <div>
          <p className="text-caption font-medium tracking-wide text-primary uppercase">Paper → test → result</p>
          <h3 id="claim-workbench-title" className="mt-1 text-h3 text-text">Claim-to-experiment workbench</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
            Test the paper’s scaling mechanism with a paired synthetic attention experiment. Search is restricted to this project’s papers;
            choose the passages that support the claim before running it.
          </p>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)]">
        <div className="space-y-3">
          <label htmlFor="workbench-claim" className="block text-small font-medium text-text">Paper claim under test</label>
          <textarea
            id="workbench-claim"
            value={claim}
            onChange={(event) => {
              setClaim(event.target.value)
              setEvidenceSearch(null)
              setSelectedEvidence([])
            }}
            placeholder="For example: scaling dot-product attention by √dₖ keeps softmax away from saturated regions as key dimension grows."
            maxLength={600}
            rows={3}
            className="w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-small leading-relaxed text-text placeholder:text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setClaim(TRANSFORMER_CLAIM)
                setEvidenceSearch(null)
                setSelectedEvidence([])
              }}
            >
              <Sparkles className="size-3.5" aria-hidden /> Use Transformer example
            </Button>
            <Button
              variant="secondary"
              onClick={search}
              loading={findEvidence.isPending}
              disabled={claim.trim().length < 12}
            >
              <Search className="size-4" aria-hidden /> Find paper evidence
            </Button>
          </div>
          {evidenceSearch && (
            <div className="space-y-3 rounded-lg border border-border bg-surface-muted p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-small font-medium text-text">
                  {evidenceSearch.passages.length} passages from {evidenceSearch.paper_count} project paper(s)
                </p>
                <span className="text-caption text-muted">Select up to five citations</span>
              </div>
              {evidenceSearch.passages.map((passage, index) => {
                const checked = selectedEvidence.includes(passage.chunk_id)
                const disabled = !checked && selectedEvidence.length >= 5
                return (
                  <div key={passage.chunk_id} className="rounded-md border border-border bg-surface p-3">
                    <label className="mb-2 flex w-fit cursor-pointer items-center gap-2 text-caption font-medium text-text">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggleEvidence(passage.chunk_id)}
                        className="size-4 accent-[var(--primary)]"
                      />
                      Attach this passage as evidence
                    </label>
                    <SourceCard item={toEvidenceItem(passage, index + 1)} reranker={null} quoteLimit={520} />
                  </div>
                )
              })}
              {evidenceSearch.passages.length === 0 && (
                <p className="text-small text-muted">Try a shorter claim or check that its paper is indexed in this project.</p>
              )}
            </div>
          )}
        </div>

        <div className="space-y-4 rounded-lg bg-surface-muted p-4">
          <div>
            <h4 className="text-small font-semibold text-text">Stress-test settings</h4>
            <p className="mt-1 text-caption leading-relaxed text-muted">
              Both variants use the same sampled queries and keys. Only the score divisor changes.
            </p>
          </div>
          <fieldset>
            <legend className="text-caption font-medium text-text">Key dimensions dₖ (choose 2–5)</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {DIMENSION_CHOICES.map((dimension) => (
                <label key={dimension} className="flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-small text-text">
                  <input
                    type="checkbox"
                    checked={dimensions.includes(dimension)}
                    disabled={!dimensions.includes(dimension) && dimensions.length >= 5}
                    onChange={() => toggleDimension(dimension)}
                    className="accent-[var(--primary)]"
                  />
                  {dimension}
                </label>
              ))}
            </div>
          </fieldset>
          <Field
            label="Random seed"
            type="number"
            min={0}
            max={2_147_483_647}
            step={1}
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            description="Reuse the seed to reproduce the same synthetic Q/K vectors."
          />
          <div className="rounded-md border border-border bg-surface p-3 text-caption leading-relaxed text-muted">
            <p><span className="font-medium text-text">Paper baseline:</span> softmax(QKᵀ / √dₖ)</p>
            <p className="mt-1"><span className="font-medium text-text">Ablation:</span> softmax(QKᵀ) without scaling</p>
          </div>
          <Button
            className="w-full"
            onClick={() => {
              setViewRunId(null)
              runAction.mutate({
                claim: claim.trim(),
                evidence_chunk_ids: selectedEvidence,
                dimensions,
                seed: parsedSeed,
              })
            }}
            loading={runAction.isPending}
            disabled={!canRun}
          >
            <FlaskConical className="size-4" aria-hidden /> Run claim stress test
          </Button>
          {!project.hypothesis.trim() && (
            <p className="text-caption text-warning">Add your own hypothesis in Gap & hypothesis to save it alongside this claim.</p>
          )}
        </div>
      </div>

      {displayedRun && (
        <div className="space-y-3 border-t border-border pt-5">
          {runs.length > 1 && (
            <details className="rounded-md border border-border px-3 py-2">
              <summary className="cursor-pointer text-small font-medium text-text">Run history · {runs.length} saved</summary>
              <ul className="mt-2 space-y-1">
                {runs.map((run) => (
                  <li key={run.id}>
                    <button
                      type="button"
                      onClick={() => setViewRunId(run.id)}
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-small text-muted hover:bg-surface-muted hover:text-text"
                    >
                      {displayedRun.id === run.id && <Check className="size-3.5 text-primary" aria-hidden />}
                      <span>{new Date(run.created_at).toLocaleString()}</span>
                      <span className="truncate">{run.claim}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <StressTestResults run={displayedRun} />
        </div>
      )}
    </section>
  )
}

function StressTestResults({ run }: { run: ClaimStressTestRun }) {
  const evidence = run.evidence.map(toEvidenceItem)
  return (
    <article aria-labelledby={`stress-result-${run.id}`} className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 id={`stress-result-${run.id}`} className="text-h3 text-text">Experiment result</h4>
            <Badge tone="success">Saved</Badge>
          </div>
          <p className="mt-1 text-caption text-muted">
            {new Date(run.created_at).toLocaleString()} · seed {run.seed} · {run.query_count} queries × {run.key_count} keys per dimension
          </p>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Snapshot label="Paper claim" text={run.claim} />
        <Snapshot label="Project question" text={run.question} />
        <Snapshot label="Your hypothesis" text={run.hypothesis || 'No hypothesis was recorded for this run.'} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <MetricChart run={run} metric="saturated_query_rate" title="Queries with a saturated softmax row" />
        <MetricChart run={run} metric="normalized_entropy" title="Normalized attention entropy" />
      </div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[760px] border-collapse text-left text-caption">
          <caption className="px-3 py-2 text-left text-small font-semibold text-text">Results by key dimension · saturation means max attention ≥ 0.95</caption>
          <thead className="bg-surface-muted text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">dₖ</th>
              <th className="px-3 py-2 font-medium">Logit SD · scaled / raw</th>
              <th className="px-3 py-2 font-medium">Saturated queries · scaled / raw</th>
              <th className="px-3 py-2 font-medium">Entropy · scaled / raw</th>
              <th className="px-3 py-2 font-medium">Gradient proxy · scaled / raw</th>
            </tr>
          </thead>
          <tbody>
            {run.results.map((row) => (
              <tr key={row.key_dimension} className="border-t border-border text-text">
                <th scope="row" className="px-3 py-2 font-mono">{row.key_dimension}</th>
                <td className="px-3 py-2 font-mono tabular-nums">{row.paper_scaled.logit_std.toFixed(2)} / {row.unscaled.logit_std.toFixed(2)}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{asPercent(row.paper_scaled.saturated_query_rate)} / {asPercent(row.unscaled.saturated_query_rate)}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{row.paper_scaled.mean_entropy_nats.toFixed(2)} / {row.unscaled.mean_entropy_nats.toFixed(2)} nats</td>
                <td className="px-3 py-2 font-mono tabular-nums">{row.paper_scaled.mean_softmax_gradient_proxy.toFixed(4)} / {row.unscaled.mean_softmax_gradient_proxy.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,0.8fr)]">
        <div className="space-y-3 rounded-lg border border-primary/20 bg-primary-soft p-4">
          <h5 className="text-small font-semibold text-text">What this run suggests</h5>
          <p className="text-small leading-relaxed text-text">{run.interpretation}</p>
          <p className="text-caption leading-relaxed text-muted">{run.limitation}</p>
          <details>
            <summary className="cursor-pointer text-caption font-medium text-muted">Simulation assumptions</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-caption leading-relaxed text-muted">
              {run.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
            </ul>
          </details>
        </div>
        <ExampleWeights run={run} />
      </div>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,0.8fr)]">
        <div className="rounded-lg border border-border p-4">
          <h5 className="text-small font-semibold text-text">Evidence attached to this run</h5>
          <div className="mt-3 space-y-4">
            {evidence.map((source) => <SourceCard key={source.chunk_id} item={source} reranker={null} quoteLimit={520} />)}
          </div>
        </div>
        <div className="space-y-3 rounded-lg border border-border p-4">
          <h5 className="text-small font-semibold text-text">How to read this test</h5>
          <p className="text-small leading-relaxed text-muted">
            Under the stated assumptions, raw dot-product variance grows with dₖ. Dividing by √dₖ is expected to keep
            the softmax inputs at a steadier scale. Higher saturation and a smaller p(1−p) proxy indicate weaker local
            softmax sensitivity in this synthetic sample.
          </p>
          <p className="text-caption leading-relaxed text-muted">
            The retrieved passages document the paper claim. They do not certify the simulation or establish that your
            project hypothesis is true.
          </p>
        </div>
      </div>
    </article>
  )
}

function Snapshot({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded-md bg-surface-muted p-3">
      <p className="text-caption font-medium text-muted">{label}</p>
      <p className="mt-1 text-small leading-relaxed text-text">{text}</p>
    </div>
  )
}

type ChartMetric = 'saturated_query_rate' | 'normalized_entropy'

function MetricChart({ run, metric, title }: { run: ClaimStressTestRun; metric: ChartMetric; title: string }) {
  const width = 520
  const height = 230
  const left = 48
  const right = 16
  const top = 18
  const bottom = 38
  const chartWidth = width - left - right
  const chartHeight = height - top - bottom
  const x = (index: number) => left + (run.results.length === 1 ? chartWidth / 2 : index * chartWidth / (run.results.length - 1))
  const y = (value: number) => top + chartHeight * (1 - value)
  const series = [
    { key: 'paper_scaled' as const, label: 'Paper scaling ÷ √dₖ', color: 'var(--viz-1)' },
    { key: 'unscaled' as const, label: 'No scaling', color: 'var(--viz-2)' },
  ]
  return (
    <section className="rounded-lg border border-border p-3">
      <h5 className="text-small font-semibold text-text">{title}</h5>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title} across key dimensions, comparing paper scaling and no scaling`} className="mt-2 w-full overflow-visible">
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke="var(--viz-grid)" strokeWidth="1" />
            <text x={left - 8} y={y(tick) + 4} textAnchor="end" fill="var(--text-muted)" fontSize="11">
              {metric === 'saturated_query_rate' ? `${Math.round(tick * 100)}%` : tick.toFixed(1)}
            </text>
          </g>
        ))}
        {run.results.map((row, index) => (
          <g key={row.key_dimension}>
            <line x1={x(index)} x2={x(index)} y1={top} y2={top + chartHeight} stroke="var(--viz-grid)" strokeWidth="1" strokeDasharray="2 4" />
            <text x={x(index)} y={height - 10} textAnchor="middle" fill="var(--text-muted)" fontSize="11">{row.key_dimension}</text>
          </g>
        ))}
        {series.map((item) => {
          const points = run.results.map((row, index) => `${x(index)},${y(row[item.key][metric])}`).join(' ')
          return (
            <g key={item.key}>
              <polyline points={points} fill="none" stroke={item.color} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
              {run.results.map((row, index) => (
                <circle key={row.key_dimension} cx={x(index)} cy={y(row[item.key][metric])} r="4" fill={item.color}>
                  <title>{`${item.label}, dₖ ${row.key_dimension}: ${metric === 'saturated_query_rate' ? asPercent(row[item.key][metric]) : row[item.key][metric].toFixed(3)}`}</title>
                </circle>
              ))}
            </g>
          )
        })}
        <text x={left + chartWidth / 2} y={height - 1} textAnchor="middle" fill="var(--text-muted)" fontSize="11">Key dimension dₖ</text>
      </svg>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-caption text-muted">
        {series.map((item) => (
          <span key={item.key} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ backgroundColor: item.color }} aria-hidden />{item.label}
          </span>
        ))}
      </div>
    </section>
  )
}

function ExampleWeights({ run }: { run: ClaimStressTestRun }) {
  const example = run.largest_dimension_example
  return (
    <section className="space-y-3 rounded-lg border border-border p-4">
      <div>
        <h5 className="text-small font-semibold text-text">One query at dₖ={example.key_dimension}</h5>
        <p className="mt-1 text-caption text-muted">Each cell is its softmax weight across the 12 keys.</p>
      </div>
      <WeightRow label="Paper scaled" values={example.paper_scaled} />
      <WeightRow label="Unscaled" values={example.unscaled} />
    </section>
  )
}

function WeightRow({ label, values }: { label: string; values: number[] }) {
  return (
    <div>
      <p className="mb-1 text-caption font-medium text-muted">{label}</p>
      <div className="flex gap-1" role="img" aria-label={`${label} key attention weights: ${values.map((value) => value.toFixed(3)).join(', ')}`}>
        {values.map((value, index) => (
          <span
            key={index}
            title={`Key ${index + 1}: ${value.toFixed(4)}`}
            className="flex h-9 min-w-0 flex-1 items-center justify-center rounded-sm font-mono text-[0.6rem] tabular-nums"
            style={{
              backgroundColor: `rgba(53, 81, 212, ${Math.min(0.9, 0.12 + value * 1.8)})`,
              color: value > 0.38 ? 'white' : 'var(--text)',
            }}
          >
            {value.toFixed(2)}
          </span>
        ))}
      </div>
    </div>
  )
}

function asPercent(value: number) {
  return `${(value * 100).toFixed(0)}%`
}
