import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '@/lib/queryClient'
import { documentsApi } from '@/services/api'
import { ApiError } from '@/services/http'
import type { DocumentDetail } from '@/types/api'
import { MetadataDialog } from './MetadataDialog'

afterEach(() => vi.restoreAllMocks())

const doc = { id: 'd1', title: 'r.pdf', metadata: null } as unknown as DocumentDetail

function open(onOpenChange = vi.fn()) {
  render(
    <QueryClientProvider client={queryClient}>
      <MetadataDialog doc={doc} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return onOpenChange
}

describe('Fill from DOI', () => {
  it('needs a DOI first, then fills the details from it and closes', async () => {
    const fill = vi.spyOn(documentsApi, 'fillFromDoi').mockResolvedValue({ ...doc, title: 'Optuna' })
    const onOpenChange = open()
    const button = screen.getByRole('button', { name: 'Fill from DOI' })
    expect(button).toBeDisabled()
    await userEvent.type(screen.getByLabelText('DOI'), '  10.1145/3292500.3330701 ')
    await userEvent.click(button)
    expect(fill).toHaveBeenCalledWith('d1', '10.1145/3292500.3330701')
    await vi.waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('says why when the DOI can’t be used, and stays open', async () => {
    vi.spyOn(documentsApi, 'fillFromDoi').mockRejectedValue(
      new ApiError(422, { code: 'validation_error', message: 'Crossref has no record of this DOI.', hint: null }),
    )
    const onOpenChange = open()
    await userEvent.type(screen.getByLabelText('DOI'), '10.0000/missing')
    await userEvent.click(screen.getByRole('button', { name: 'Fill from DOI' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Crossref has no record of this DOI.')
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })
})
