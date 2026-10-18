import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { collectionsApi, projectsApi, watchesApi } from '@/services/api'
import type { Watch } from '@/types/api'
import { WatchDialog } from './WatchDialog'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

afterEach(() => vi.restoreAllMocks())

const watch = (over: Partial<Watch> = {}): Watch => ({
  id: 'w1',
  name: 'Adapters',
  query: 'low rank adapters',
  collection_id: null,
  project_id: null,
  interval_hours: 24,
  relevance_threshold: 0.35,
  auto_import: false,
  synthesize: false,
  is_public: false,
  status: 'active',
  last_searched_at: null,
  next_run_at: new Date().toISOString(),
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  latest_run: null,
  ...over,
})

describe('WatchDialog', () => {
  it('disables submit until name and topic are filled, then creates with defaults', async () => {
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])
    const create = vi.spyOn(watchesApi, 'create').mockResolvedValue(watch())
    const onOpenChange = vi.fn()
    render(wrap(<WatchDialog open onOpenChange={onOpenChange} />))

    const submit = screen.getByRole('button', { name: 'Create' })
    expect(submit).toBeDisabled()

    await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'Adapters')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByRole('textbox', { name: 'Topic / search terms' }), 'low rank adapters')
    expect(submit).not.toBeDisabled()

    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    expect(checkboxes).toHaveLength(3) // auto_import, synthesize, is_public
    expect(checkboxes.every((c) => !c.checked)).toBe(true)
    await userEvent.click(submit)
    expect(create).toHaveBeenCalledWith({
      name: 'Adapters',
      query: 'low rank adapters',
      collection_id: null,
      project_id: null,
      interval_hours: 24,
      relevance_threshold: 0.35,
      auto_import: false,
      synthesize: false,
      is_public: false,
    })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('edits an existing watch, prefilling its fields', async () => {
    vi.spyOn(collectionsApi, 'list').mockResolvedValue([])
    vi.spyOn(projectsApi, 'list').mockResolvedValue([])
    const existing = watch({ auto_import: true, synthesize: true, interval_hours: 6 })
    const update = vi.spyOn(watchesApi, 'update').mockResolvedValue(existing)
    render(wrap(<WatchDialog open onOpenChange={vi.fn()} watch={existing} />))

    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Adapters')
    const [autoImport, synthesize, isPublic] = screen.getAllByRole('checkbox') as HTMLInputElement[]
    expect(autoImport.checked).toBe(true)
    expect(synthesize.checked).toBe(true)
    expect(isPublic.checked).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(update).toHaveBeenCalledWith('w1', expect.objectContaining({ name: 'Adapters' }))
  })
})
