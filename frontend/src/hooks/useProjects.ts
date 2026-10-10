import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { projectsApi } from '@/services/api'
import type { Project } from '@/types/api'

export function useProjects() {
  return useQuery({ queryKey: ['projects', 'list'], queryFn: projectsApi.list })
}

const busy = (p: Project | undefined) =>
  !!p &&
  (p.steps.questions.status === 'running' ||
    p.steps.outline.status === 'running' ||
    [p.reports.background, p.reports.gaps].some((r) => r && (r.status === 'queued' || r.status === 'running')))

export function useProject(id: string) {
  return useQuery({
    queryKey: ['projects', 'detail', id],
    queryFn: () => projectsApi.get(id),
    refetchInterval: (query) => (busy(query.state.data) ? 2500 : false),
  })
}

/** Any project action: the response is the updated project. */
export function useProjectAction<T>(id: string, action: (input: T) => Promise<Project>, success?: string) {
  return useMutation({
    mutationFn: action,
    onSuccess: (project) => {
      queryClient.setQueryData(['projects', 'detail', id], project)
      void queryClient.invalidateQueries({ queryKey: ['projects', 'list'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      if (success) toast.success(success)
    },
    onError: (error: Error) => toast.error(error.message),
  })
}
