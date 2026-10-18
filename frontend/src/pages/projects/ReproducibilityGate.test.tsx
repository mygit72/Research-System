import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { Project, StarterFile } from '@/types/api'
import { ReproducibilityGate } from './ReproducibilityGate'
import { auditMarkdown, runReproducibilityAudit } from './reproducibilityAudit'

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'project-1',
    title: 'Retriever experiment',
    idea: 'Compare retrieval variants.',
    question: 'Does adapting the retriever improve exact match?',
    hypothesis: 'The adapted retriever improves exact match by at least 2 points.',
    collection_id: null,
    created_at: '2026-10-13T00:00:00Z',
    updated_at: '2026-10-13T00:00:00Z',
    completion: { questions: false, background: false, gaps: false, methods: false, experiments: false, outline: false },
    reports: { background: null, gaps: null },
    progress: null,
    steps: {
      questions: { status: 'idle', suggestions: [], sources: [], error: null },
      background: { report_id: null },
      gaps: { report_id: null, chosen: null },
      methods: { suggestions: {}, chosen: { datasets: ['SQuAD'], baselines: ['BM25'], methods: ['Dense retrieval'], metrics: ['Exact match'] } },
      experiments: {
        items: [
          { key: 'main', kind: 'main', title: 'Compare systems', setup: 'Same validation split', goal: 'Compare exact match', metrics: ['Exact match'], notes: '' },
          { key: 'ablation', kind: 'ablation', title: 'Remove adaptation', setup: 'Disable adapter', goal: 'Test contribution', metrics: ['Exact match'], notes: '' },
        ],
        milestones: [], deadline: null,
        result_analyses: [], prediction_analyses: [],
      },
      outline: { status: 'idle', sections: [], sources: [], error: null },
      code: { status: 'idle', drafts: {}, note: null, error: null },
    },
    ...overrides,
  }
}

const goodFiles: StarterFile[] = [
  { path: 'config.json', purpose: 'Experiment plan', content: JSON.stringify({ split: 'validation', seeds: [1, 2, 3] }) },
  { path: 'run_experiments.py', purpose: 'Run experiments', content: 'for seed in seeds:\n    pass\n"results.csv"' },
  { path: 'requirements.txt', purpose: 'Packages', content: 'numpy==2.0.0\npytest==8.0.0' },
  { path: 'test_pipeline.py', purpose: 'Pipeline tests', content: 'def test_runner_smoke():\n    assert True' },
]

describe('runReproducibilityAudit', () => {
  it('checks the saved plan and reproducibility files using explicit findings', () => {
    const findings = runReproducibilityAudit(makeProject(), goodFiles)
    expect(findings.find((finding) => finding.id === 'seeds')).toMatchObject({ status: 'pass', detail: '3 seeds configured (1, 2, 3).' })
    expect(findings.find((finding) => finding.id === 'runner')).toMatchObject({ status: 'pass' })
    expect(findings.find((finding) => finding.id === 'dependencies')).toMatchObject({ status: 'pass' })
    expect(findings.find((finding) => finding.id === 'ablation')).toMatchObject({ status: 'pass' })

    const unpinned = runReproducibilityAudit(makeProject(), goodFiles.map((file) =>
      file.path === 'requirements.txt' ? { ...file, content: 'numpy>=2.0.0' } : file,
    ))
    expect(unpinned.find((finding) => finding.id === 'dependencies')?.status).toBe('warning')
  })

  it('flags test-set use, missing outputs and malformed config as problems', () => {
    const project = makeProject({ question: '', hypothesis: '' })
    const files = goodFiles.map((file) => file.path === 'config.json'
      ? { ...file, content: '{invalid json' }
      : file.path === 'run_experiments.py'
        ? { ...file, content: 'print("hello")' }
        : file)
    const findings = runReproducibilityAudit(project, files)
    expect(findings.find((finding) => finding.id === 'question')?.status).toBe('blocked')
    expect(findings.find((finding) => finding.id === 'hypothesis')?.status).toBe('blocked')
    expect(findings.find((finding) => finding.id === 'config')?.status).toBe('blocked')
    expect(findings.find((finding) => finding.id === 'runner')?.status).toBe('warning')
    expect(findings.find((finding) => finding.id === 'results')?.status).toBe('warning')

    const testSplit = runReproducibilityAudit(makeProject(), [
      ...goodFiles.filter((file) => file.path !== 'config.json'),
      { ...goodFiles[0], content: JSON.stringify({ split: 'test', seeds: [1, 2, 3] }) },
    ])
    expect(testSplit.find((finding) => finding.id === 'split')).toMatchObject({ status: 'blocked' })
  })

  it('exports a report that states the audit scope and current finding', () => {
    const project = makeProject()
    const findings = runReproducibilityAudit(project, goodFiles)
    const report = auditMarkdown(project, findings, new Date('2026-10-13T00:00:00Z'))
    expect(report).toContain('# Reproducibility preflight: Retriever experiment')
    expect(report).toContain('## PASS · Repeated random seeds')
    expect(report).toContain('does not execute code')
  })
})

describe('ReproducibilityGate', () => {
  it('shows actionable preflight findings and accurately says it does not execute code', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ReproducibilityGate project={makeProject()} files={goodFiles} />
      </MemoryRouter>,
    )
    await user.click(screen.getByRole('button', { name: 'Run preflight' }))
    const summary = screen.getByRole('status')
    expect(within(summary).getByText('13 passed')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Review methods' })[0]).toHaveAttribute('href', '/projects/project-1?step=methods')
    expect(screen.getByText(/does not execute code/)).toBeInTheDocument()
  })
})
