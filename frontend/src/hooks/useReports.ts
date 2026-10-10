import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { reportsApi } from '@/services/api'
import type { ReportKind, ReportRequest } from '@/types/api'

export function useReports(kind?: ReportKind) {
  return useQuery({
    queryKey: ['reports', 'list', kind ?? 'all'],
    queryFn: () => reportsApi.list(kind),
    // Keep the list fresh while something is being written.
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === 'queued' || r.status === 'running') ? 3000 : false,
  })
}

export function useReport(id: string) {
  return useQuery({
    queryKey: ['reports', 'detail', id],
    queryFn: () => reportsApi.get(id),
    enabled: id !== '', // an empty id would request "/reports/" (a redirect the CSP blocks)
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 1500 : false
    },
  })
}

export function useCreateReport() {
  return useMutation({
    mutationFn: ({ kind, body }: { kind: ReportKind; body: ReportRequest }) => reportsApi.create(kind, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['reports'] }),
    onError: (error: Error) => toast.error(error.message),
  })
}

export function useUpdateReport(id: string) {
  return useMutation({
    mutationFn: (body: { title?: string; sections?: { key: string; title?: string; text?: string }[] }) =>
      reportsApi.update(id, body),
    onSuccess: (report) => {
      queryClient.setQueryData(['reports', 'detail', id], report)
      void queryClient.invalidateQueries({ queryKey: ['reports', 'list'] })
      toast.success('Saved')
    },
    onError: (error: Error) => toast.error(error.message),
  })
}

export function useDeleteReport() {
  return useMutation({
    mutationFn: (id: string) => reportsApi.remove(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['reports'] }),
    onError: (error: Error) => toast.error(error.message),
  })
}
