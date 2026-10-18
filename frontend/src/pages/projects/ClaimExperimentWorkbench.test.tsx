import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { projectsApi } from '@/services/api'
import type { ClaimEvidenceSearch, ClaimStressTestRun, Project } from '@/types/api'
import { ClaimExperimentWorkbench } from './ClaimExperimentWorkbench'

afterEach(() => vi.restoreAllMocks())

const passage: ClaimEvidenceSearch['passages'][number] = {
  chunk_id: 'chunk-1',
  document_id: 'paper-1',
  title: 'Attention Is All You Need',
  year: 2017,
  section_title: 'Scaled Dot-Product Attention',
  page_start: 4,
  page_end: 4,
  char_start: 200,
  boxes: [],
  quote: 'We suspect that for large values of dₖ, the dot products grow large in magnitude, pushing the softmax function into regions where it has extremely small gradients.',
}

const run: ClaimStressTestRun = {
  id: 'run-1',
  created_at: '2026-10-13T12:00:00Z',
  runner: 'paired_gaussian_attention_stress_v1',
  seed: 42,
  claim: 'Scaling dot-product attention avoids softmax saturation for large key dimensions.',
  question: 'How does scaling affect attention?',
  hypothesis: 'Scaling keeps gradients useful.',
  dimensions: [4, 16, 64, 256],
  query_count: 24,
  key_count: 12,
  saturation_threshold: 0.95,
  results: [4, 16, 64, 256].map((key_dimension) => ({
    key_dimension,
    paper_scaled: {
      logit_std: 1,
      mean_entropy_nats: 2,
      normalized_entropy: 0.8,
      mean_max_probability: 0.3,
      saturated_query_rate: 0,
      mean_softmax_gradient_proxy: 0.06,
    },
    unscaled: {
      logit_std: 8,
      mean_entropy_nats: 0.3,
      normalized_entropy: 0.1,
      mean_max_probability: 0.9,
      saturated_query_rate: key_dimension === 256 ? 0.6 : 0.2,
      mean_softmax_gradient_proxy: 0.01,
    },
  })),
  largest_dimension_example: {
    key_dimension: 256,
    paper_scaled: Array.from({ length: 12 }, () => 1 / 12),
    unscaled: [0.7, ...Array.from({ length: 11 }, () => 0.3 / 11)],
  },
  interpretation: 'The unscaled run saturated more often.',
  assumptions: ['Synthetic unit-normal query and key vectors.'],
  limitation: 'This is not a reproduction of the paper results.',
  evidence: [passage],
}

const project = (claimRuns: ClaimStressTestRun[] = []): Project => ({
  id: 'project-1',
  title: 'Attention study',
  idea: 'Study scaled dot-product attention.',
  question: 'How does scaling affect attention?',
  hypothesis: 'Scaling keeps gradients useful.',
  collection_id: 'collection-1',
  created_at: '2026-10-13T11:00:00Z',
  updated_at: '2026-10-13T11:00:00Z',
  completion: { questions: true, background: false, gaps: true, methods: false, experiments: true, outline: false },
  guidance: null,
  reports: { background: null, gaps: null },
  progress: null,
  steps: {
    questions: { status: 'ready', suggestions: [], sources: [], error: null },
    background: { report_id: null },
    gaps: { report_id: null, chosen: null },
    methods: { suggestions: {}, chosen: { datasets: [], baselines: [], methods: [], metrics: [] } },
    experiments: { items: [], milestones: [], deadline: null, claim_runs: claimRuns },
    outline: { status: 'idle', sections: [], sources: [], error: null },
    code: { status: 'idle', drafts: {}, note: null, error: null },
  },
})

function wrap(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('ClaimExperimentWorkbench', () => {
  it('finds project evidence, runs a seeded stress test and displays saved results', async () => {
    const user = userEvent.setup()
    const search: ClaimEvidenceSearch = { claim: run.claim, status: 'ok', paper_count: 1, passages: [passage] }
    vi.spyOn(projectsApi, 'findClaimEvidence').mockResolvedValue(search)
    vi.spyOn(projectsApi, 'runClaimStressTest').mockResolvedValue(project([run]))
    wrap(<ClaimExperimentWorkbench project={project()} />)

    await user.click(screen.getByRole('button', { name: /Use Transformer example/ }))
    await user.click(screen.getByRole('button', { name: 'Find paper evidence' }))
    expect(await screen.findByText(/We suspect that for large values/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Attach this passage as evidence' })).toBeChecked()

    await user.click(screen.getByRole('button', { name: 'Run claim stress test' }))
    expect(projectsApi.runClaimStressTest).toHaveBeenCalledWith('project-1', {
      claim: expect.stringContaining('Scaling dot-product attention'),
      evidence_chunk_ids: ['chunk-1'],
      dimensions: [4, 16, 64, 256],
      seed: 42,
    })
    expect(await screen.findByRole('heading', { name: 'Experiment result' })).toBeInTheDocument()
    expect(screen.getByText('The unscaled run saturated more often.')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Queries with a saturated softmax row across key dimensions/ })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Open paper' })).toHaveLength(2)
  })
})
