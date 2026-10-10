import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { knowledgeApi } from '@/services/api'
import type { ClusterMethod, EntityType, TimelineFilters } from '@/types/api'

/** Knowledge views derive from papers, metadata and topics: refresh them together. */
export function refreshKnowledge() {
  void queryClient.invalidateQueries({ queryKey: ['knowledge'] })
}

export function useGraph(params: { types: string; limit: number; focus?: string; includeMentions: boolean }) {
  return useQuery({
    queryKey: ['knowledge', 'graph', params],
    queryFn: () => knowledgeApi.graph(params),
    placeholderData: keepPreviousData,
  })
}

export function useEntities(params: { type?: EntityType; q?: string; includeMentions?: boolean }) {
  return useQuery({
    queryKey: ['knowledge', 'entities', params],
    queryFn: () => knowledgeApi.entities(params),
    placeholderData: keepPreviousData,
  })
}

export function useEntity(id: string) {
  return useQuery({ queryKey: ['knowledge', 'entity', id], queryFn: () => knowledgeApi.entity(id) })
}

export function useDocumentEntities(id: string, enabled = true) {
  return useQuery({
    queryKey: ['knowledge', 'document-entities', id],
    queryFn: () => knowledgeApi.documentEntities(id),
    enabled,
  })
}

export function useRelatedWork(id: string, enabled = true) {
  return useQuery({ queryKey: ['knowledge', 'related', id], queryFn: () => knowledgeApi.related(id), enabled })
}

export function useAuthors(q?: string) {
  return useQuery({
    queryKey: ['knowledge', 'authors', q ?? ''],
    queryFn: () => knowledgeApi.authors(q),
    placeholderData: keepPreviousData,
  })
}

export function useAuthor(key: string) {
  return useQuery({ queryKey: ['knowledge', 'author', key], queryFn: () => knowledgeApi.author(key) })
}

export function useTimeline(filters: TimelineFilters) {
  return useQuery({
    queryKey: ['knowledge', 'timeline', filters],
    queryFn: () => knowledgeApi.timeline(filters),
    placeholderData: keepPreviousData,
  })
}

export function useTopics() {
  return useQuery({
    queryKey: ['knowledge', 'topics'],
    queryFn: knowledgeApi.topics,
    // Names arrive from a background job: poll until it's done.
    refetchInterval: (query) => (query.state.data?.clustering?.naming_status === 'pending' ? 2000 : false),
  })
}

export function useCluster() {
  return useMutation({
    mutationFn: (body: { method: ClusterMethod; k?: number; min_cluster_size?: number }) => knowledgeApi.cluster(body),
    onSuccess: () => refreshKnowledge(),
    onError: (error: Error) => toast.error(error.message),
  })
}
