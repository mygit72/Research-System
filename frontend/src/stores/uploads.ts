/**
 * Upload manager: a small queue (3 concurrent uploads) with per-file progress.
 * Lives outside React so uploads continue while the user navigates.
 */
import { toast } from 'sonner'
import { create } from 'zustand'
import { queryClient } from '@/lib/queryClient'
import { documentsApi } from '@/services/api'
import { ApiError } from '@/services/http'

export const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.markdown', '.html', '.htm']
export const ACCEPTED_LABEL = 'PDF, DOCX, TXT, Markdown, HTML'
const CONCURRENCY = 3

export type UploadState = 'pending' | 'uploading' | 'uploaded' | 'error'

export interface UploadItem {
  id: string
  file: File
  state: UploadState
  progress: number
  documentId?: string
  duplicate?: boolean
  error?: string
  hint?: string | null
}

interface UploadsState {
  items: UploadItem[]
  dialogOpen: boolean
  maxSizeMb: number
  setDialogOpen: (open: boolean) => void
  setMaxSizeMb: (mb: number) => void
  add: (files: File[]) => void
  retry: (id: string) => void
  clearFinished: () => void
}

/** Checks we can do instantly in the browser; the server re-validates everything. */
export function precheck(file: File, maxSizeMb: number): string | null {
  const name = file.name.toLowerCase()
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext)))
    return `This file type isn't supported. Upload ${ACCEPTED_LABEL}.`
  if (file.size === 0) return 'This file is empty.'
  if (file.size > maxSizeMb * 1024 * 1024) return `This file is larger than the ${maxSizeMb} MB limit.`
  return null
}

let nextId = 0

export const useUploads = create<UploadsState>((set, get) => {
  const update = (id: string, patch: Partial<UploadItem>) =>
    set((state) => ({
      items: state.items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    }))

  const pump = () => {
    const { items } = get()
    const active = items.filter((i) => i.state === 'uploading').length
    const queued = items.filter((i) => i.state === 'pending').slice(0, CONCURRENCY - active)
    queued.forEach((item) => void run(item))
  }

  const run = async (item: UploadItem) => {
    update(item.id, { state: 'uploading', progress: 0 })
    try {
      const response = await documentsApi.upload(item.file, (progress) =>
        update(item.id, { progress }),
      )
      const doc = response.items[0]
      if (doc) {
        update(item.id, {
          state: 'uploaded',
          progress: 1,
          documentId: doc.id,
          duplicate: doc.duplicate_kind === 'exact_duplicate',
        })
      } else {
        const error = response.errors[0]
        update(item.id, { state: 'error', error: error?.message, hint: error?.hint })
      }
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    } catch (error) {
      update(item.id, {
        state: 'error',
        error: error instanceof ApiError ? error.message : 'Upload failed.',
        hint: error instanceof ApiError ? error.hint : null,
      })
    } finally {
      const { items } = get()
      if (!items.some((i) => i.state === 'pending' || i.state === 'uploading')) {
        const done = items.filter((i) => i.state === 'uploaded').length
        const failed = items.filter((i) => i.state === 'error').length
        if (done && !get().dialogOpen)
          toast.success(`${done} paper${done === 1 ? '' : 's'} uploaded. Processing has started.`)
        if (failed && !get().dialogOpen)
          toast.error(`${failed} file${failed === 1 ? '' : 's'} couldn't be uploaded.`)
      }
      pump()
    }
  }

  return {
    items: [],
    dialogOpen: false,
    maxSizeMb: 50,
    setDialogOpen: (dialogOpen) => set({ dialogOpen }),
    setMaxSizeMb: (maxSizeMb) => set({ maxSizeMb }),
    add: (files) => {
      const { maxSizeMb } = get()
      const items: UploadItem[] = files.map((file) => {
        const problem = precheck(file, maxSizeMb)
        return {
          id: `u${nextId++}`,
          file,
          state: problem ? 'error' : 'pending',
          progress: 0,
          error: problem ?? undefined,
        }
      })
      set((state) => ({ items: [...items, ...state.items] }))
      pump()
    },
    retry: (id) => {
      update(id, { state: 'pending', error: undefined, hint: undefined, progress: 0 })
      pump()
    },
    clearFinished: () =>
      set((state) => ({
        items: state.items.filter((i) => i.state === 'pending' || i.state === 'uploading'),
      })),
  }
})
