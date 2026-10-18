import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { projectsApi } from '@/services/api'
import type { ExperimentResultsAnalysis, PaperRunMatch, Project } from '@/types/api'
import { ExperimentResultsLab } from './ExperimentResultsLab'

afterEach(() => vi.restoreAllMocks())

const csv = `experiment,dataset,system,seed,metric,value,status,note
main-1,toy,baseline,1,Exact match,0.50,ok,
main-1,toy,proposed,1,Exact match,0.60,ok,`

const analysis: ExperimentResultsAnalysis = {
  id: 'analysis-1',
  created_at: '2026-10-13T12:00:00Z',
  filename: 'results.csv',
  rows_seen: 2,
  rows_analyzed: 2,
  status_counts: { ok: 2 },
  issues: [],
  summaries: [
    { experiment: 'main-1', dataset: 'toy', system: 'baseline', metric: 'Exact match', seed_count: 1, mean: 0.5, std: 0 },
    { experiment: 'main-1', dataset: 'toy', system: 'proposed', metric: 'Exact match', seed_count: 1, mean: 0.6, std: 0 },
  ],
  comparisons: [
    {
      experiment: 'main-1',
      dataset: 'toy',
      metric: 'Exact match',
      system_a: 'baseline',
      system_b: 'proposed',
      paired_seed_count: 1,
      mean_difference: 0.1,
      ci95_lower: null,
      ci95_upper: null,
    },
  ],
  notes: ['Δ is system B minus system A.'],
}
const matchAnalysis: ExperimentResultsAnalysis = {
  ...analysis,
  summaries: [
    { experiment: 'main-1', dataset: 'SQuAD', system: 'BM25', metric: 'Exact match', seed_count: 3, mean: 0.5, std: 0.01 },
  ],
  comparisons: [],
}

const initialProject = {
  id: 'project-1',
  reports: { background: null, gaps: null },
  steps: {
    questions: { status: 'idle', sources: [] },
    outline: { status: 'idle', sources: [] },
    code: { status: 'idle' },
    experiments: { items: [], milestones: [], deadline: null, result_analyses: [], paper_run_matches: [], claim_runs: [] },
  },
} as unknown as Project

const savedProject = {
  ...initialProject,
  steps: { ...initialProject.steps, experiments: { ...initialProject.steps.experiments, result_analyses: [analysis] } },
} as unknown as Project

const citedSource = {
  number: 1,
  chunk_id: 'chunk-1',
  document: { id: 'paper-1', title: 'A Retrieval Paper', year: 2024 },
  section_title: 'Results',
  page_start: 4,
  page_end: 4,
  char_start: 120,
  boxes: [],
  quote: 'BM25 obtains an exact match score of 0.50 on the validation split.',
  score: 0.9,
}
const sourcedProject = {
  ...savedProject,
  question: 'Compare retrieval baselines.',
  hypothesis: 'BM25 will reach 0.50 exact match.',
  steps: {
    ...savedProject.steps,
    questions: { sources: [citedSource] },
    experiments: { ...savedProject.steps.experiments, result_analyses: [matchAnalysis], paper_run_matches: [] },
    outline: { sources: [] },
  },
} as unknown as Project

const savedMatch: PaperRunMatch = {
  id: 'match-1', created_at: '2026-10-13T12:00:00Z', status: 'within_tolerance', alignment: 'exact',
  label_mismatches: [], split_matches: true, mapping_note: null,
  reported_mean: 0.5, reproduced_mean: 0.5, difference: 0, absolute_difference: 0,
  relative_difference_percent: 0, tolerance: 0.02,
  paper: { document_id: 'paper-1', title: 'A Retrieval Paper', year: 2024, chunk_id: 'chunk-1', section_title: 'Results', page_start: 4, page_end: 4, char_start: 120, boxes: [], quote: citedSource.quote, kind: 'text' },
  reported: { dataset: 'SQuAD', system: 'BM25', metric: 'Exact match', split: 'validation', mean: 0.5, std: null },
  run: { analysis_id: 'analysis-1', filename: 'results.csv', experiment: 'main-1', dataset: 'SQuAD', system: 'BM25', metric: 'Exact match', split: 'validation', mean: 0.5, std: 0.01, seed_count: 3 },
}

function wrap(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('ExperimentResultsLab', () => {
  it('uploads the runner CSV, saves its analysis and explains paired results', async () => {
    const user = userEvent.setup()
    vi.spyOn(projectsApi, 'analyzeResults').mockResolvedValue(savedProject)
    wrap(<ExperimentResultsLab project={initialProject} />)

    const file = new File([csv], 'results.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'text', { value: async () => csv })
    await user.upload(screen.getByLabelText('Choose results CSV'), file)
    await user.click(screen.getByRole('button', { name: 'Analyze results' }))

    expect(projectsApi.analyzeResults).toHaveBeenCalledWith('project-1', csv, 'results.csv')
    expect(await screen.findByRole('heading', { name: 'Analysis · results.csv' })).toBeInTheDocument()
    expect(screen.getByText(/baseline → proposed/)).toBeInTheDocument()
    expect(screen.getByText('Need ≥2 shared seeds')).toBeInTheDocument()
    expect(screen.getByText(/fewer than five paired seeds/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Paper-to-Run Match' })).toBeInTheDocument()
  })

  it('saves a cited paper result against an imported run summary and shows the comparison', async () => {
    const user = userEvent.setup()
    const withMatch = {
      ...sourcedProject,
      steps: {
        ...sourcedProject.steps,
        experiments: { ...sourcedProject.steps.experiments, paper_run_matches: [savedMatch] },
      },
    } as Project
    vi.spyOn(projectsApi, 'get').mockResolvedValue(sourcedProject)
    const createMatch = vi.spyOn(projectsApi, 'createPaperRunMatch').mockResolvedValue(withMatch)
    wrap(<ExperimentResultsLab project={sourcedProject} />)

    await user.type(screen.getByRole('textbox', { name: 'Paper dataset' }), 'SQuAD')
    await user.type(screen.getByRole('textbox', { name: 'Paper system or baseline' }), 'BM25')
    await user.type(screen.getByRole('textbox', { name: 'Paper metric' }), 'Exact match')
    await user.type(screen.getByRole('textbox', { name: 'Paper evaluation split' }), 'validation')
    await user.type(screen.getByRole('textbox', { name: /Run evaluation split/ }), 'validation')
    await user.type(screen.getByRole('spinbutton', { name: 'Reported mean' }), '0.5')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Cited paper passage' }), 'chunk-1')
    await user.click(screen.getByRole('button', { name: 'Save paper-to-run comparison' }))

    expect(createMatch).toHaveBeenCalledWith('project-1', expect.objectContaining({
      result_analysis_id: 'analysis-1',
      run_experiment: 'main-1',
      run_dataset: 'SQuAD',
      run_system: 'BM25',
      run_metric: 'Exact match',
      run_split: 'validation',
      evidence_chunk_id: 'chunk-1',
      reported_mean: 0.5,
      tolerance: 0.02,
    }))
    expect(await screen.findByText('Within tolerance')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /A Retrieval Paper · p. 4/ })).toBeInTheDocument()
    expect(screen.getByText(/Labels and split aligned/)).toBeInTheDocument()
  })
})
