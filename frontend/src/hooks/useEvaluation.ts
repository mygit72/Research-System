import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { evaluationApi } from '@/services/api'

const refresh = () => void queryClient.invalidateQueries({ queryKey: ['evaluation'] })
const onError = (error: Error) => toast.error(error.message)

export function useDatasets() {
  return useQuery({
    queryKey: ['evaluation', 'datasets'],
    queryFn: evaluationApi.datasets,
    refetchInterval: (q) => (q.state.data?.some((d) => d.generation.status === 'running') ? 3000 : false),
  })
}

export function useItems(datasetId: string | null) {
  return useQuery({
    queryKey: ['evaluation', 'items', datasetId],
    queryFn: () => evaluationApi.items(datasetId!),
    enabled: !!datasetId,
  })
}

export function useRuns() {
  return useQuery({
    queryKey: ['evaluation', 'runs'],
    queryFn: () => evaluationApi.runs(),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'queued' || r.status === 'running') ? 2000 : false),
  })
}

export function useRun(id: string) {
  return useQuery({
    queryKey: ['evaluation', 'run', id],
    queryFn: () => evaluationApi.run(id),
    refetchInterval: (q) => (q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 2000 : false),
  })
}

export function useEvalAction<T, R>(action: (input: T) => Promise<R>, success?: string) {
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      refresh()
      if (success) toast.success(success)
    },
    onError,
  })
}
