import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { watchesApi } from '@/services/api'
import type { WatchCreate, WatchUpdate } from '@/types/api'

export function refreshWatches() {
  for (const key of ['watches', 'documents', 'collections'])
    void queryClient.invalidateQueries({ queryKey: [key] })
}

export function useWatches() {
  return useQuery({ queryKey: ['watches', 'list'], queryFn: watchesApi.list })
}

export function useWatch(id: string) {
  return useQuery({ queryKey: ['watches', id], queryFn: () => watchesApi.get(id) })
}

export function useWatchRuns(id: string) {
  return useQuery({ queryKey: ['watches', id, 'runs'], queryFn: () => watchesApi.runs(id) })
}

export function useWatchDigest(id: string) {
  return useQuery({ queryKey: ['watches', id, 'digest'], queryFn: () => watchesApi.digest(id) })
}

const onError = (error: Error) => toast.error(error.message)

export function useCreateWatch() {
  return useMutation({
    mutationFn: (body: WatchCreate) => watchesApi.create(body),
    onSuccess: () => {
      toast.success('Watch created')
      refreshWatches()
    },
    onError,
  })
}

export function useUpdateWatch(id: string) {
  return useMutation({
    mutationFn: (body: WatchUpdate) => watchesApi.update(id, body),
    onSuccess: () => {
      toast.success('Watch updated')
      refreshWatches()
    },
    onError,
  })
}

export function useDeleteWatch() {
  return useMutation({
    mutationFn: (id: string) => watchesApi.remove(id),
    onSuccess: () => {
      toast.success('Watch deleted')
      refreshWatches()
    },
    onError,
  })
}

export function useRunWatchNow(id: string) {
  return useMutation({
    mutationFn: () => watchesApi.runNow(id),
    onSuccess: () => {
      toast.success('Running now')
      refreshWatches()
    },
    onError,
  })
}

export function useImportDigestEntry(watchId: string) {
  return useMutation({
    mutationFn: (entryId: string) => watchesApi.importEntry(watchId, entryId),
    onSuccess: (entry) => {
      toast.success(entry.import_status === 'imported' ? 'Added to your library' : 'Already in your library')
      void queryClient.invalidateQueries({ queryKey: ['watches', watchId, 'digest'] })
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
    onError,
  })
}
