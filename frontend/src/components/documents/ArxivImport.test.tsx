import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseRefs } from '@/lib/arxivRefs'
import { documentsApi } from '@/services/api'
import { ApiError } from '@/services/http'
import type { UploadResponse } from '@/types/api'
import { ArxivImportButton } from './ArxivImport'

afterEach(() => vi.restoreAllMocks())

const renderButton = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ArxivImportButton />
    </QueryClientProvider>,
  )

const imported = { items: [{ id: 'd1' }], errors: [] } as unknown as UploadResponse

async function open(text: string) {
  await userEvent.click(screen.getByRole('button', { name: /Import from arXiv/ }))
  await userEvent.click(screen.getByRole('textbox', { name: 'arXiv ids, links or DOIs' }))
  await userEvent.paste(text)
}

describe('parseRefs', () => {
  it('splits on lines, spaces and commas, and drops repeats', () => {
    expect(parseRefs('2310.11511\n https://arxiv.org/abs/2112.09118, 2310.11511 ')).toEqual([
      '2310.11511',
      'https://arxiv.org/abs/2112.09118',
    ])
    expect(parseRefs('  \n ')).toEqual([])
  })
})

describe('ArxivImportButton', () => {
  it('imports each paper and closes when all succeed', async () => {
    const importPapers = vi.spyOn(documentsApi, 'importPapers').mockResolvedValue(imported)
    renderButton()
    await open('2310.11511\n2112.09118')
    await userEvent.click(screen.getByRole('button', { name: 'Import 2 papers' }))
    expect(importPapers).toHaveBeenCalledTimes(2)
    expect(importPapers).toHaveBeenNthCalledWith(1, ['2310.11511'])
    expect(importPapers).toHaveBeenNthCalledWith(2, ['2112.09118'])
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('keeps the dialog open with each failure, and only the failed ids left to fix', async () => {
    vi.spyOn(documentsApi, 'importPapers').mockImplementation((refs) =>
      refs[0] === 'nonsense'
        ? Promise.reject(new ApiError(422, { code: 'validation_error', message: '“nonsense” isn’t an arXiv id or link.', hint: 'Use an id like 2310.11511.' }))
        : Promise.resolve(imported),
    )
    renderButton()
    await open('2310.11511 nonsense')
    await userEvent.click(screen.getByRole('button', { name: 'Import 2 papers' }))
    expect(await screen.findByText(/isn’t an arXiv id or link/)).toBeInTheDocument()
    expect(screen.getByText(/Use an id like 2310.11511/)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'arXiv ids, links or DOIs' })).toHaveValue('nonsense')
  })

  it('refuses more than ten at once and needs at least one', async () => {
    const importPapers = vi.spyOn(documentsApi, 'importPapers')
    renderButton()
    await userEvent.click(screen.getByRole('button', { name: /Import from arXiv/ }))
    expect(screen.getByRole('button', { name: 'Import paper' })).toBeDisabled()
    await userEvent.click(screen.getByRole('textbox', { name: 'arXiv ids, links or DOIs' }))
    await userEvent.paste(Array.from({ length: 11 }, (_, i) => `2310.${11500 + i}`).join('\n'))
    expect(screen.getByRole('alert')).toHaveTextContent('up to 10 papers')
    expect(screen.getByRole('button', { name: 'Import 11 papers' })).toBeDisabled()
    expect(importPapers).not.toHaveBeenCalled()
  })
})
