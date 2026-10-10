import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { CollectionPage } from '@/pages/collections/CollectionPage'
import * as http from '@/services/http'
import { chatApi, collectionsApi, notesApi, organizationApi, tagsApi } from '@/services/api'
import type { CollectionDetail, DocumentOrganization, DocumentSummary, Note } from '@/types/api'
import { NotesList } from './Notes'
import { TagEditor } from './Tags'

function wrap(children: ReactNode, path = '/', route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={children} />
            <Route path="/chat/:id" element={<p>Opened chat</p>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

const org = (tags: string[]): DocumentOrganization => ({
  tags: tags.map((name, i) => ({ id: `t${i}`, name, color: null })),
  reading_status: null,
  bookmarked: false,
  collections: [],
})

describe('TagEditor', () => {
  it('adds a tag with Enter (ignoring a leading #) and removes one with its ×', async () => {
    vi.spyOn(tagsApi, 'list').mockResolvedValue([])
    const setTags = vi.spyOn(organizationApi, 'setTags').mockResolvedValue(org(['PEFT', 'baseline']))
    render(wrap(<TagEditor documentId="d1" tags={org(['PEFT']).tags} />))
    await userEvent.click(screen.getByRole('button', { name: /Tag/ }))
    await userEvent.type(screen.getByRole('combobox', { name: 'New tag' }), '#baseline{Enter}')
    expect(setTags).toHaveBeenLastCalledWith('d1', ['PEFT', 'baseline'])
    await userEvent.click(screen.getByRole('button', { name: 'Remove tag PEFT' }))
    expect(setTags).toHaveBeenLastCalledWith('d1', [])
  })

  it('does not add a tag the paper already has, in any case', async () => {
    vi.spyOn(tagsApi, 'list').mockResolvedValue([])
    const setTags = vi.spyOn(organizationApi, 'setTags')
    render(wrap(<TagEditor documentId="d1" tags={org(['PEFT']).tags} />))
    await userEvent.click(screen.getByRole('button', { name: /Tag/ }))
    await userEvent.type(screen.getByRole('combobox', { name: 'New tag' }), 'peft{Enter}')
    expect(setTags).not.toHaveBeenCalled()
  })
})

const note = (overrides: Partial<Note> = {}): Note => ({
  id: 'n1',
  content: '**Compare** with prefix tuning.',
  document_id: 'd1',
  collection_id: null,
  anchor: { type: 'passage', page: 3, quote: 'rank-8 adapters', boxes: [[3, 1, 2, 3, 4]] },
  document_title: 'Low-Rank Adapters',
  created_at: '2026-10-02T10:00:00Z',
  updated_at: '2026-10-02T10:00:00Z',
  ...overrides,
})

describe('NotesList', () => {
  it('shows Markdown notes with their passage, opens it, and saves new paper notes', async () => {
    vi.spyOn(notesApi, 'list').mockResolvedValue([note()])
    const create = vi.spyOn(notesApi, 'create').mockResolvedValue(note({ id: 'n2' }))
    const onOpen = vi.fn()
    render(wrap(<NotesList documentId="d1" onOpenAnchor={onOpen} />))
    expect(await screen.findByText('Compare', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText('“rank-8 adapters”')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Show/ }))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 'n1' }))

    await userEvent.click(screen.getByRole('button', { name: /Add note/ }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Note' }), 'Check the rank ablation')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))
    expect(create).toHaveBeenCalledWith({
      content: 'Check the rank ablation',
      document_id: 'd1',
      collection_id: undefined,
      anchor: { type: 'paper' },
    })
  })

  it('edits and deletes a note', async () => {
    vi.spyOn(notesApi, 'list').mockResolvedValue([note()])
    const update = vi.spyOn(notesApi, 'update').mockResolvedValue(note({ content: 'Edited' }))
    const remove = vi.spyOn(notesApi, 'remove').mockResolvedValue()
    render(wrap(<NotesList documentId="d1" />))
    await userEvent.click(await screen.findByRole('button', { name: 'Edit note' }))
    const box = screen.getByRole('textbox', { name: 'Note' })
    await userEvent.clear(box)
    await userEvent.type(box, 'Edited{Control>}{Enter}{/Control}')
    expect(update).toHaveBeenCalledWith('n1', 'Edited')
    await userEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    expect(remove).toHaveBeenCalledWith('n1')
  })
})

describe('CollectionPage', () => {
  const paper = (id: string, title: string): DocumentSummary =>
    ({
      id,
      title,
      status: 'ready',
      index_status: 'indexed',
      doc_type: 'pdf',
      authors_display: 'Wei',
      year: 2023,
      reading_status: 'reading',
      tags: [{ id: 't1', name: 'PEFT', color: null }],
      bookmarked: false,
    }) as DocumentSummary
  const collection: CollectionDetail = {
    id: 'c1',
    name: 'Thesis ch. 2',
    description: 'Parameter-efficient tuning',
    kind: 'thesis',
    paper_count: 2,
    note_count: 0,
    created_at: '2026-10-02T10:00:00Z',
    updated_at: '2026-10-02T10:00:00Z',
    documents: [paper('d1', 'Low-Rank Adapters'), paper('d2', 'Hybrid Retrieval')],
  }

  it('lists its papers, exports BibTeX, removes a paper and starts a chat about it', async () => {
    vi.spyOn(collectionsApi, 'get').mockResolvedValue(collection)
    vi.spyOn(notesApi, 'list').mockResolvedValue([])
    const raw = vi.spyOn(http, 'request').mockResolvedValue('@misc{wei2023lowrank}')
    const removePaper = vi.spyOn(collectionsApi, 'removePaper').mockResolvedValue()
    const chat = vi.spyOn(chatApi, 'create').mockResolvedValue({ id: 'conv1' } as never)
    const createUrl = vi.fn(() => 'blob:x')
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: vi.fn() }))
    render(wrap(<CollectionPage />, '/collections/c1', '/collections/:id'))

    expect(await screen.findByRole('heading', { name: 'Thesis ch. 2' })).toBeInTheDocument()
    expect(screen.getByText('Thesis')).toBeInTheDocument()
    expect(screen.getAllByText('#')).toHaveLength(2) // tag chips
    expect(screen.getByRole('button', { name: /Compare/ })).toBeEnabled()

    await userEvent.click(screen.getByRole('button', { name: /Export/ }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /BibTeX/ }))
    expect(raw).toHaveBeenCalledWith('/collections/c1/export?format=bibtex', { raw: true })
    await vi.waitFor(() => expect(createUrl).toHaveBeenCalled())

    const row = screen.getByText('Low-Rank Adapters').closest('li')!
    await userEvent.click(within(row).getByRole('button', { name: /Remove/ }))
    expect(removePaper).toHaveBeenCalledWith('c1', 'd1')

    await userEvent.click(screen.getByRole('button', { name: /Chat/ }))
    expect(chat).toHaveBeenCalledWith({ collection_id: 'c1', title: 'About Thesis ch. 2' })
    expect(await screen.findByText('Opened chat')).toBeInTheDocument()
  })
})
