import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { collectionsApi, projectsApi } from '@/services/api'
import type { Project } from '@/types/api'
import { ProjectPage } from './ProjectPage'
import { ProjectsPage } from './ProjectsPage'

function wrap(children: ReactNode, path: string, route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={children} />
            <Route path="/projects/:id" element={<p>Opened project</p>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

const project = (over: Partial<Project> = {}): Project => ({
  id: 'p1',
  title: 'Retriever-aware generators',
  idea: 'Adapt generators to their retriever with low-rank adapters.',
  question: '',
  hypothesis: '',
  collection_id: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  completion: { questions: false, background: false, gaps: false, methods: false, experiments: false, outline: false },
  reports: { background: null, gaps: null },
  progress: null,
  steps: {
    questions: {
      status: 'ready',
      suggestions: [{ text: 'Does adapting the generator improve exact match?', citations: [1], papers: ['Hybrid retrieval'], status: 'supported' }],
      sources: [{ number: 1, chunk_id: 'c1', document: { id: 'd1', title: 'Hybrid retrieval', year: 2024 }, section_title: 'Results', page_start: 3, page_end: 3, char_start: 0, boxes: [], quote: 'Passage.' }],
      error: null,
    },
    background: { report_id: null },
    gaps: { report_id: null, chosen: null },
    methods: {
      suggestions: {
        dataset: [{ entity_id: 'e1', name: 'SciQA-2400', papers: [{ id: 'd1', title: 'Hybrid retrieval', year: 2024 }], count: 3, proposed_by: 0, info: {} }],
        metric: [{ entity_id: 'e2', name: 'Exact match', papers: [], count: 2, proposed_by: 0, info: {} }],
      },
      chosen: { datasets: [], baselines: [], methods: [], metrics: [] },
      paper_count: 3,
    },
    experiments: { items: [], milestones: [], deadline: null },
    outline: { status: 'idle', sections: [], sources: [], error: null },
    code: { status: 'idle', drafts: {}, note: null, error: null },
  },
  ...over,
}) // fmt: skip

describe('ProjectsPage', () => {
  it('starts a project from an idea', async () => {
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    const create = vi.spyOn(projectsApi, 'create').mockResolvedValue(project())
    render(wrap(<ProjectsPage />, '/projects', '/projects'))
    const start = await screen.findByRole('button', { name: /Start project/ })
    expect(start).toBeDisabled()
    await userEvent.type(screen.getByRole('textbox', { name: 'Your idea' }), 'Adapt generators to retrievers')
    await userEvent.click(start)
    expect(create).toHaveBeenCalledWith({ idea: 'Adapt generators to retrievers', collection_id: null })
    expect(await screen.findByText('Opened project')).toBeInTheDocument()
  })

  it('starts a paper-scoped project with the source paper attached', async () => {
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    const createCollection = vi.spyOn(collectionsApi, 'create').mockResolvedValue({
      id: 'paper-collection',
      name: 'Research: Attention Is All You Need',
      description: '',
      kind: 'project',
      paper_count: 1,
      note_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })
    const createProject = vi.spyOn(projectsApi, 'create').mockResolvedValue(project())
    const idea = 'Build on Attention Is All You Need with a small, testable extension.'
    render(
      wrap(
        <ProjectsPage />,
        `/projects?paper_id=paper-1&paper_title=${encodeURIComponent('Attention Is All You Need')}&idea=${encodeURIComponent(idea)}`,
        '/projects',
      ),
    )
    expect(await screen.findByText(/Starting paper:/)).toHaveTextContent('Attention Is All You Need')
    expect(screen.getByRole('textbox', { name: 'Your idea' })).toHaveValue(idea)
    await userEvent.click(screen.getByRole('button', { name: /Start project/ }))
    expect(createCollection).toHaveBeenCalledWith({
      name: 'Research: Attention Is All You Need',
      description: expect.stringContaining('Attention Is All You Need'),
      kind: 'project',
      document_ids: ['paper-1'],
    })
    expect(createProject).toHaveBeenCalledWith({
      idea,
      collection_id: 'paper-collection',
    })
    expect(await screen.findByText('Opened project')).toBeInTheDocument()
  })
})

describe('ProjectPage', () => {
  it('uses a suggested question, citing where it comes from', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(project())
    const update = vi.spyOn(projectsApi, 'update').mockResolvedValue(project({ question: 'x' }))
    render(wrap(<ProjectPage />, '/projects/p1', '/projects/:id'))
    expect(await screen.findByRole('heading', { level: 1, name: 'Retriever-aware generators' })).toBeInTheDocument()
    expect(screen.getByText('0 of 6 steps done')).toBeInTheDocument()
    expect(screen.getByText(/Builds on Hybrid retrieval/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Use this question' }))
    expect(screen.getByRole('textbox', { name: 'Your research question' })).toHaveValue(
      'Does adapting the generator improve exact match?',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Save question' }))
    expect(update).toHaveBeenCalledWith('p1', { question: 'Does adapting the generator improve exact match?' })
  })

  it('says what to do next and warns about a thin library', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(
      project({
        guidance: {
          next_step: { step: 'background', message: 'Run the background review to see what the papers say.' },
          notes: ['The project has 2 papers. Add 2 or more related papers to its collection.'],
        },
      }),
    )
    render(wrap(<ProjectPage />, '/projects/p1', '/projects/:id'))
    const guidance = await screen.findByRole('region', { name: 'Guidance' })
    expect(within(guidance).getByText(/Run the background review/)).toBeInTheDocument()
    expect(within(guidance).getByText(/The project has 2 papers/)).toBeInTheDocument()
    await userEvent.click(within(guidance).getByRole('button', { name: 'Go to Background' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Background' })).toBeInTheDocument()
  })

  it('links a collection from the project page, so the advice to add papers can be followed', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(
      project({ guidance: { next_step: { step: 'questions', message: 'Write your question.' }, notes: [] } }),
    )
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([
      { id: 'c1', name: 'RAG thesis', paper_count: 6 },
    ] as Awaited<ReturnType<typeof collectionsApi.list>>)
    const update = vi.spyOn(projectsApi, 'update').mockResolvedValue(project({ collection_id: 'c1' }))
    render(wrap(<ProjectPage />, '/projects/p1', '/projects/:id'))
    const select = await screen.findByRole('combobox', { name: 'Papers for this project' })
    expect(select).toHaveValue('')
    await userEvent.selectOptions(select, 'c1')
    expect(update).toHaveBeenCalledWith('p1', { collection_id: 'c1' })
  })

  it('chooses methods from what the papers use, and adds your own', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(project())
    const update = vi.spyOn(projectsApi, 'update').mockResolvedValue(project())
    render(wrap(<ProjectPage />, '/projects/p1?step=methods', '/projects/:id'))
    const datasets = await screen.findByRole('group', { name: /Datasets/ })
    await userEvent.click(within(datasets).getByRole('button', { name: /SciQA-2400/ }))
    const metrics = screen.getByRole('group', { name: /Metrics/ })
    await userEvent.type(within(metrics).getByRole('textbox', { name: 'Add to Metrics' }), 'F1{Enter}')
    await userEvent.click(screen.getByRole('button', { name: 'Save method plan' }))
    expect(update).toHaveBeenCalledWith('p1', {
      methods: { datasets: ['SciQA-2400'], baselines: [], methods: [], metrics: ['F1'] },
    })
    expect(screen.getByText('From 3 papers.')).toBeInTheDocument()
  })

  it('plans experiments with a deadline', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(project())
    const planned = project()
    planned.steps.experiments = {
      items: [{ key: 'main-1', kind: 'main', title: 'Main comparison on SciQA-2400', goal: 'Test it.', setup: 'LoRA vs. full fine-tuning', metrics: ['Exact match'], notes: '' }],
      milestones: [{ title: 'Write the paper', due: '2027-01-01', done: false }],
      deadline: '2027-01-10',
    }
    const plan = vi.spyOn(projectsApi, 'planExperiments').mockResolvedValue(planned)
    render(wrap(<ProjectPage />, '/projects/p1?step=experiments', '/projects/:id'))
    await userEvent.click(await screen.findByRole('button', { name: 'Plan experiments' }))
    expect(plan).toHaveBeenCalledWith('p1', { deadline: undefined, replace: false })
    expect(await screen.findByRole('textbox', { name: 'Experiment title' })).toHaveValue('Main comparison on SciQA-2400')
    expect(screen.getByRole('checkbox', { name: 'Done: Write the paper' })).not.toBeChecked()
  })

  it('needs a question before drafting the outline', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(project())
    render(wrap(<ProjectPage />, '/projects/p1?step=outline', '/projects/:id'))
    expect(await screen.findByRole('button', { name: /Draft the outline/ })).toBeDisabled()
    expect(screen.getByText('Choose a research question first.')).toBeInTheDocument()
  })
})
