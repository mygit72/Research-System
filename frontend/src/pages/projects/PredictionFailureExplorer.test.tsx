import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { projectsApi } from '@/services/api'
import type { PredictionAnalysis, Project } from '@/types/api'
import { PredictionFailureExplorer } from './PredictionFailureExplorer'

afterEach(() => vi.restoreAllMocks())

const jsonlText = [
  { system: 'baseline', seed: 1, question: 'What is the answer?', metric_scores: { exact_match: 0 } },
  { system: 'proposed', seed: 1, question: 'What is the answer?', metric_scores: { exact_match: 1 } },
].map((row) => JSON.stringify(row)).join('\n')

const analysis: PredictionAnalysis = {
  id: 'analysis-1',
  created_at: '2026-10-13T12:00:00Z',
  filename: 'predictions_main-1.jsonl',
  metric: 'exact_match',
  higher_is_better: true,
  records_seen: 2,
  records_scored: 2,
  records_without_metric: 0,
  example_count: 1,
  systems: ['baseline', 'proposed'],
  metrics: ['exact_match'],
  summaries: [
    { system: 'baseline', scored_predictions: 1, mean_score: 0 },
    { system: 'proposed', scored_predictions: 1, mean_score: 1 },
  ],
  hard_case_count: 1,
  cases: [
    {
      experiment: 'main-1',
      dataset: 'toy',
      example_id: '0',
      question: 'What is the answer?',
      reference_answers: ['the answer'],
      reference_passages: [{ index: 0, text: 'The reference source.' }],
      systems: [
        {
          system: 'baseline',
          mean_score: 0,
          scored_seeds: 1,
          run_count: 1,
          runs: [{ seed: '1', score: 0, answer: 'A wrong guess.', used_passages: [], retrieved_passages: [] }],
        },
        {
          system: 'proposed',
          mean_score: 1,
          scored_seeds: 1,
          run_count: 1,
          runs: [{ seed: '1', score: 1, answer: 'The answer.', used_passages: [], retrieved_passages: [] }],
        },
      ],
      best_system_score: 1,
      score_spread: 1,
    },
  ],
  notes: ['Only compact results are saved.'],
}

const initialProject = {
  id: 'project-1',
  steps: { experiments: { items: [], milestones: [], deadline: null } },
} as unknown as Project

const savedProject = {
  ...initialProject,
  steps: { experiments: { items: [], milestones: [], deadline: null, prediction_analyses: [analysis] } },
} as unknown as Project

function wrap(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('PredictionFailureExplorer', () => {
  it('imports scored predictions and compares answers against references', async () => {
    const user = userEvent.setup()
    vi.spyOn(projectsApi, 'analyzePredictions').mockResolvedValue(savedProject)
    wrap(<PredictionFailureExplorer project={initialProject} />)

    const file = new File([jsonlText], 'predictions_main-1.jsonl', { type: 'application/x-ndjson' })
    Object.defineProperty(file, 'text', { value: async () => jsonlText })
    await user.upload(screen.getByLabelText('Choose prediction JSONL'), file)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze hard cases' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Analyze hard cases' }))

    expect(projectsApi.analyzePredictions).toHaveBeenCalledWith(
      'project-1', jsonlText, 'predictions_main-1.jsonl', 'exact_match', true,
    )
    expect(await screen.findByRole('heading', { name: 'Hard cases · exact_match' })).toBeInTheDocument()
    expect(screen.getByText('What is the answer?')).toBeInTheDocument()
    expect(screen.getByText('A wrong guess.')).toBeInTheDocument()
    expect(screen.getByText('The answer.')).toBeInTheDocument()
    expect(screen.getByText('the answer')).toBeInTheDocument()
  })
})
