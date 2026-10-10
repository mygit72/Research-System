import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { documentsApi } from '@/services/api'
import { ApiError } from '@/services/http'
import type { ZipImportResponse } from '@/types/api'
import { ZipImportButton } from './ZipImport'

afterEach(() => vi.restoreAllMocks())

const renderButton = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ZipImportButton />
      </MemoryRouter>
    </QueryClientProvider>,
  )

const zip = new File(['PK'], 'papers.zip', { type: 'application/zip' })

async function pick() {
  await userEvent.click(screen.getByRole('button', { name: /Import zip/ }))
  await userEvent.upload(screen.getByLabelText('Zip file'), zip)
}

describe('ZipImportButton', () => {
  it('needs a file before it can import', async () => {
    renderButton()
    await userEvent.click(screen.getByRole('button', { name: /Import zip/ }))
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
    await userEvent.upload(screen.getByLabelText('Zip file'), zip)
    expect(screen.getByRole('button', { name: 'Import' })).toBeEnabled()
  })

  it('imports into a named collection and reports what happened, with reasons', async () => {
    const importZip = vi.spyOn(documentsApi, 'importZip').mockResolvedValue({
      items: [{ id: 'a' }, { id: 'b' }],
      errors: [{ filename: 'broken.pdf', message: 'Not a valid PDF.', hint: null }],
      skipped: [{ filename: 'figure.png', reason: 'Not a supported file type.' }],
      collection_id: 'c1',
    } as unknown as ZipImportResponse)
    renderButton()
    await pick()
    await userEvent.type(screen.getByLabelText('Put the papers in a new collection'), 'Thesis reading')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(importZip).toHaveBeenCalledWith(zip, 'Thesis reading', expect.any(Function))
    expect(await screen.findByRole('status')).toHaveTextContent('2 papers imported')
    expect(screen.getByRole('link', { name: 'Open the new collection' })).toHaveAttribute('href', '/collections/c1')
    expect(screen.getByRole('alert')).toHaveTextContent('broken.pdf: Not a valid PDF.')
    expect(screen.getByText('1 file skipped')).toBeInTheDocument()
    expect(screen.getByText(/figure\.png:/)).toBeInTheDocument()
  })

  it('shows why the whole archive was refused and stays open', async () => {
    vi.spyOn(documentsApi, 'importZip').mockRejectedValue(
      new ApiError(422, { code: 'validation_error', message: 'The archive holds 101 papers; the limit is 100 at a time.', hint: 'Split it into smaller zips.' }),
    )
    renderButton()
    await pick()
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The archive holds 101 papers')
    expect(screen.getByLabelText('Zip file')).toBeInTheDocument()
  })
})
