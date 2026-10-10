import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { summariesApi } from '@/services/api'
import type { PaperSummary } from '@/types/api'

export const summaryKey = (documentId: string) => ['summaries', documentId] as const

export const isWriting = (summary: PaperSummary | null | undefined) =>
  summary?.status === 'queued' || summary?.status === 'running'

/** The paper's summary. Polls while it's being written (sections appear as they're done). */
export function useSummary(documentId: string, enabled = true) {
  return useQuery({
    queryKey: summaryKey(documentId),
    queryFn: () => summariesApi.get(documentId),
    enabled,
    refetchInterval: (query) => (isWriting(query.state.data) ? 1500 : false),
  })
}

export function useGenerateSummary(documentId: string) {
  return useMutation({
    mutationFn: (force: boolean) => summariesApi.generate(documentId, force),
    onSuccess: (summary) => {
      queryClient.setQueryData(summaryKey(documentId), summary)
      void queryClient.invalidateQueries({ queryKey: summaryKey(documentId) })
    },
    onError: (error) => toast.error(error.message),
  })
}
