import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { MemoryRouter } from 'react-router-dom'
import { projectsApi } from '@/services/api'
import type { Project, StepGuide } from '@/types/api'
import { StarterCodeStep } from './StarterCode'
import { StepGuidePanel } from './StepGuide'

afterEach(() => vi.restoreAllMocks())

const wrap = (children: ReactNode) => (
  <TooltipProvider>
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        {children}
      </QueryClientProvider>
    </MemoryRouter>
  </TooltipProvider>
)

const guide: StepGuide = {
  step: 'methods',
  number: 4,
  of: 7,
  title: 'Methods',
  why: 'Reviewers ask compared to what.',
  actions: [
    { title: 'Choose datasets', detail: 'Pick one your papers report on.' },
    { title: 'Choose baselines', detail: 'The strongest your papers report.' },
    { title: 'Choose metrics', detail: 'The ones those papers use.' },
  ],
  expected: 'Lists you can defend in a sentence.',
  checks: ['Can you point to a paper for each metric?'],
  pitfalls: ['Choosing everything suggested.'],
  yours: ['Datasets: toy, squad', 'Baselines: none chosen'],
  previous: 'gaps',
  next: 'experiments',
}

describe('StepGuidePanel', () => {
  it('explains the step in order and reflects the project', async () => {
    const get = vi.spyOn(projectsApi, 'guide').mockResolvedValue(guide)
    render(wrap(<StepGuidePanel projectId="p1" step="methods" version="v1" />))
    expect(await screen.findByText('Reviewers ask compared to what.')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('p1', 'methods')
    expect(screen.getByRole('button', { name: /How this step works · step 4 of 7/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/Choose datasets\./)).toBeInTheDocument()
    expect(screen.getByText('Lists you can defend in a sentence.')).toBeInTheDocument()
    expect(screen.getByText('Can you point to a paper for each metric?')).toBeInTheDocument()
    expect(screen.getByText('Choosing everything suggested.')).toBeInTheDocument()
    expect(screen.getByText('Datasets: toy, squad')).toBeInTheDocument()
  })

  it('collapses, and says so when the guide can’t load', async () => {
    vi.spyOn(projectsApi, 'guide').mockResolvedValue(guide)
    render(wrap(<StepGuidePanel projectId="p1" step="methods" version="v1" />))
    await screen.findByText('Reviewers ask compared to what.')
    await userEvent.click(screen.getByRole('button', { name: /How this step works/ }))
    expect(screen.queryByText('Reviewers ask compared to what.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /How this step works/ })).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows a plain message on failure', async () => {
    vi.spyOn(projectsApi, 'guide').mockRejectedValue(new Error('down'))
    render(wrap(<StepGuidePanel projectId="p1" step="questions" version="v1" />))
    expect(await screen.findByText('The guide couldn’t be loaded.')).toBeInTheDocument()
  })
})

describe('StarterCodeStep', () => {
  const files = [
    { path: 'README.md', purpose: 'The walkthrough.', content: '# Starter\nRun the smoke test first.' },
    { path: 'systems.py', purpose: 'The systems compared.', content: 'class YourApproach: ...' },
  ]
  const project = {
    id: 'p1',
    title: 'My project',
    updated_at: 'u1',
    steps: { code: { status: 'idle', drafts: {}, note: null, error: null } },
  } as Project

  it('lists every file with its purpose and shows the one you pick', async () => {
    vi.spyOn(projectsApi, 'code').mockResolvedValue({ files, runs: [] })
    render(wrap(<StarterCodeStep project={project} />))
    const list = await screen.findByRole('list', { name: 'Files' })
    expect(within(list).getByText('The walkthrough.')).toBeInTheDocument()
    expect(screen.getByLabelText('Contents of README.md')).toHaveTextContent('Run the smoke test first.')
    await userEvent.click(within(list).getByRole('button', { name: /systems\.py/ }))
    expect(screen.getByLabelText('Contents of systems.py')).toHaveTextContent('class YourApproach')
  })

  it('copies the open file and downloads the zip', async () => {
    vi.spyOn(projectsApi, 'code').mockResolvedValue({ files, runs: [] })
    const exportCode = vi.spyOn(projectsApi, 'export').mockResolvedValue(new Blob(['zip']))
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(wrap(<StarterCodeStep project={project} />))
    await screen.findByRole('list', { name: 'Files' })
    await userEvent.click(screen.getByRole('button', { name: /Copy/ }))
    expect(writeText).toHaveBeenCalledWith(files[0].content)
    expect(await screen.findByText('Copied')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Download \.zip/ }))
    expect(exportCode).toHaveBeenCalledWith('p1', 'code')
  })

  it('keeps an uncited model draft visible with its supplied paper passages', async () => {
    const source = {
      number: 1,
      chunk_id: 'chunk-1',
      document: { id: 'paper-1', title: 'Attention Is All You Need', year: 2017 },
      section_title: 'Scaled Dot-Product Attention',
      page_start: 4,
      page_end: 4,
      char_start: 0,
      boxes: [],
      quote: 'The dot products are scaled before softmax.',
    }
    const draftProject = {
      ...project,
      idea: 'Study scaled attention',
      question: 'How does scaling affect the weights?',
      hypothesis: 'Scaling reduces saturation.',
      steps: {
        ...project.steps,
        code: {
          status: 'ready',
          drafts: {
            model: {
              status: 'drafted',
              code: 'class ResearchModel:\n    def forward(self, values):\n        return values\n',
              sources: [source],
              note: 'The model omitted inline passage comments; review the supplied paper passages beside the code.',
            },
          },
          note: null,
          error: null,
        },
      },
    } as Project
    vi.spyOn(projectsApi, 'code').mockResolvedValue({
      files: [...files, { path: 'model.py', purpose: 'The generated model.', content: 'class ResearchModel: ...' }],
      runs: [],
    })
    render(wrap(<StarterCodeStep project={draftProject} />))

    expect(await screen.findByText(/omitted inline passage comments/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Paper evidence for this draft' })).toBeInTheDocument()
    expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument()
  })
})
