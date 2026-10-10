import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { bookmarksApi, collectionsApi, notesApi, organizationApi, tagsApi } from '@/services/api'
import type { Anchor, BookmarkKind, ReadingStatus } from '@/types/api'

/** Anything that shows papers (library, collections, search facets) may have changed. */
export function refreshOrganization() {
  for (const key of ['documents', 'collections', 'tags', 'notes', 'bookmarks', 'organization', 'search'])
    void queryClient.invalidateQueries({ queryKey: [key] })
}

export function useCollections() {
  return useQuery({ queryKey: ['collections', 'list'], queryFn: collectionsApi.list })
}

export function useTags() {
  return useQuery({ queryKey: ['tags'], queryFn: tagsApi.list, staleTime: 30_000 })
}

export function useDocumentOrganization(documentId: string, enabled = true) {
  return useQuery({
    queryKey: ['organization', documentId],
    queryFn: () => organizationApi.get(documentId),
    enabled,
  })
}

export function useNotes(params: { documentId?: string; collectionId?: string }) {
  return useQuery({ queryKey: ['notes', params], queryFn: () => notesApi.list(params) })
}

export function useBookmarks(params: { documentId?: string; kinds?: BookmarkKind[] } = {}) {
  return useQuery({ queryKey: ['bookmarks', params], queryFn: () => bookmarksApi.list(params) })
}

const onError = (error: Error) => toast.error(error.message)

export function useSetTags(documentId: string) {
  return useMutation({
    mutationFn: (names: string[]) => organizationApi.setTags(documentId, names),
    onSuccess: (data) => {
      queryClient.setQueryData(['organization', documentId], data)
      refreshOrganization()
    },
    onError,
  })
}

export function useSetReadingStatus(documentId: string) {
  return useMutation({
    mutationFn: (status: ReadingStatus | null) => organizationApi.setReadingStatus(documentId, status),
    onSuccess: (data) => {
      queryClient.setQueryData(['organization', documentId], data)
      refreshOrganization()
    },
    onError,
  })
}

export function useTogglePaperBookmark(documentId: string) {
  return useMutation({
    mutationFn: async (bookmarked: boolean) => {
      if (bookmarked) await organizationApi.unbookmarkPaper(documentId)
      else await bookmarksApi.create({ document_id: documentId, kind: 'paper' })
    },
    onSuccess: (_, wasBookmarked) => {
      toast.success(wasBookmarked ? 'Bookmark removed' : 'Paper bookmarked')
      refreshOrganization()
    },
    onError,
  })
}

export function useCreateBookmark() {
  return useMutation({
    mutationFn: bookmarksApi.create,
    onSuccess: () => {
      toast.success('Bookmarked')
      refreshOrganization()
    },
    onError,
  })
}

export function useCreateNote() {
  return useMutation({
    mutationFn: (body: { content: string; document_id?: string; collection_id?: string; anchor?: Anchor }) =>
      notesApi.create(body),
    onSuccess: () => {
      toast.success('Note saved')
      refreshOrganization()
    },
    onError,
  })
}
