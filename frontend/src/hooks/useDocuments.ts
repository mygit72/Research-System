import { useQuery } from '@tanstack/react-query'
import { documentsApi, type ListDocumentsParams } from '@/services/api'
import type { DocumentSummary } from '@/types/api'

const isBusy = (doc: Pick<DocumentSummary, 'status' | 'index_status' | 'processing'>) =>
  doc.status === 'queued' ||
  doc.status === 'processing' ||
  (doc.status === 'ready' && doc.index_status === 'pending' && doc.processing !== null)

/** Library listing. Polls every 1.5s only while some paper is still processing. */
export function useDocuments(params: ListDocumentsParams) {
  return useQuery({
    queryKey: ['documents', 'list', params],
    queryFn: () => documentsApi.list(params),
    placeholderData: (previous) => previous,
    refetchInterval: (query) => (query.state.data?.items.some(isBusy) ? 1500 : false),
  })
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: ['documents', 'detail', id],
    queryFn: () => documentsApi.get(id),
    refetchInterval: (query) => (query.state.data && isBusy(query.state.data) ? 1500 : false),
  })
}

export function useDocumentStructure(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ['documents', 'structure', id],
    queryFn: () => documentsApi.structure(id),
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useLibraryStats() {
  return useQuery({
    queryKey: ['documents', 'stats'],
    queryFn: documentsApi.stats,
    refetchInterval: (query) => ((query.state.data?.processing ?? 0) > 0 ? 3000 : false),
  })
}
