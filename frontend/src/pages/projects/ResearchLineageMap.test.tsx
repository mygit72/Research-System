import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { Project } from '@/types/api'
import { ResearchLineageMap } from './ResearchLineageMap'

const project = {
  id: 'project-1',
  title: 'Attention study',
  idea: 'Study scaled dot-product attention.',
  question: 'How does scaling affect attention?',
  hypothesis: 'Scaling keeps gradients useful.',
  steps: {
    questions: {
      sources: [{
        number: 1,
        chunk_id: 'paper-chunk-1',
        document: { id: 'paper-1', title: 'Attention Is All You Need', year: 2017 },
        section_title: 'Scaled Dot-Product Attention',
        page_start: 4,
        page_end: 4,
        char_start: 100,
        boxes: [],
        quote: 'The dot products grow large in magnitude as the key dimension grows.',
      }],
    },
    code: { drafts: {} },
    experiments: { items: [], claim_runs: [], result_analyses: [], prediction_analyses: [] },
  },
} as unknown as Project

describe('ResearchLineageMap', () => {
  it('shows separate provenance trails and does not attach unrelated sources to an unrun claim', async () => {
    render(<MemoryRouter><ResearchLineageMap project={project} /></MemoryRouter>)

    expect(screen.getByRole('region', { name: 'Paper claim → mechanism test' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Your project → implementation → observations' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Paper evidence/ }))
    expect(screen.getByText(/1 other paper source reference\(s\) exist elsewhere/)).toBeInTheDocument()
    expect(screen.getByText(/they are not linked to a saved test/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Code/ }))
    expect(screen.getByRole('link', { name: /Starter code/ })).toHaveAttribute('href', '/projects/project-1?step=code')
  })
})
