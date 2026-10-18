/** Typed endpoint functions. Components call these (via hooks), never fetch directly. */
import type {
  ActivityEvent,
  ConnectionTest,
  CodeSyntaxCheck,
  ProjectCodeRun,
  ModelChoiceRequest,
  ModelChoiceView,
  GuideStep,
  AIStatus,
  EvalDataset,
  EvalItem,
  EvalRun,
  EvalRunConfig,
  EvalRunSummary,
  Project,
  PaperRunMatchRequest,
  ClaimEvidenceSearch,
  ReferenceAttentionRun,
  ProjectSummary,
  ProjectUpdate,
  StarterFile,
  StepGuide,
  ZipImportResponse,
  Report,
  ReportKind,
  ReportRequest,
  ReportSummary,
  AuthorDetail,
  AuthorListItem,
  ClusterMethod,
  DocumentEntity,
  EntityDetail,
  EntityListItem,
  EntityType,
  GraphNode,
  KnowledgeGraph,
  RelatedWork,
  Timeline,
  TimelineFilters,
  TopicClustering,
  TopicsState,
  Anchor,
  Bookmark,
  BookmarkKind,
  Collection,
  CollectionDetail,
  CollectionKind,
  DocumentOrganization,
  Note,
  ReadingStatus,
  Tag,
  ChatEvent,
  Comparison,
  ComparisonKind,
  ComparisonSummary,
  Conversation,
  ConversationDetail,
  ChunkInfo,
  DocumentDetail,
  DocumentStatus,
  DocumentStructure,
  DocumentSummary,
  DocumentVersion,
  Job,
  LibraryStats,
  MetadataUpdate,
  Page,
  PaperSummary,
  PerformanceSummary,
  PublicConfig,
  RegisterResponse,
  SearchFacets,
  SearchRequest,
  SearchResponse,
  Session,
  SimilarPapers,
  SortKey,
  TokenResponse,
  User,
  UploadResponse,
  UsageSummary,
  UserPreferences,
  DigestEntry,
  Notification,
  PublicDigestEntry,
  PublicWatch,
  Watch,
  WatchCreate,
  WatchRun,
  WatchUpdate,
  Webhook,
  WebhookPlatform,
} from '@/types/api'
import { request, streamRequest, uploadWithProgress } from './http'

export const authApi = {
  register: (body: { email: string; password: string; full_name: string }) =>
    request<RegisterResponse>('/auth/register', { method: 'POST', body, noRetry: true }),
  login: (body: { email: string; password: string }) =>
    request<TokenResponse>('/auth/login', { method: 'POST', body, noRetry: true }),
  logout: () => request<void>('/auth/logout', { method: 'POST', noRetry: true }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<TokenResponse>('/auth/change-password', { method: 'POST', body }),
}

export const accountApi = {
  me: () => request<User>('/users/me'),
  update: (body: { full_name?: string; preferences?: UserPreferences }) =>
    request<User>('/users/me', { method: 'PATCH', body }),
  sessions: () => request<Session[]>('/users/me/sessions'),
  revokeSession: (id: string) => request<void>(`/users/me/sessions/${id}`, { method: 'DELETE' }),
  deleteAccount: () => request<void>('/users/me', { method: 'DELETE' }),
  activity: () => request<ActivityEvent[]>('/users/me/activity?limit=50'),
  exportData: () => request<Blob>('/users/me/export', { blob: true }),
}

/** The language model your AI work runs on: the server's, your own API key, or a local model. */
export const modelApi = {
  get: () => request<ModelChoiceView>('/users/me/model'),
  save: (body: ModelChoiceRequest) => request<ModelChoiceView>('/users/me/model', { method: 'PUT', body }),
  reset: () => request<ModelChoiceView>('/users/me/model', { method: 'DELETE' }),
  test: (body: { preset: string; base_url?: string; api_key?: string }) =>
    request<ConnectionTest>('/users/me/model/test', { method: 'POST', body }),
}

export const jobsApi = {
  list: (params: { status?: string[]; limit?: number } = {}) => {
    const query = new URLSearchParams()
    params.status?.forEach((s) => query.append('status', s))
    if (params.limit) query.set('limit', String(params.limit))
    return request<Page<Job>>(`/jobs?${query}`)
  },
  retry: (id: string) => request<Job>(`/jobs/${id}/retry`, { method: 'POST' }),
}

export const systemApi = {
  config: () => request<PublicConfig>('/config'),
  aiStatus: () => request<AIStatus>('/ai/status'),
}

export interface ListDocumentsParams {
  q?: string
  collectionId?: string
  tags?: string[]
  readingStatus?: ReadingStatus | 'none'
  bookmarked?: boolean
  status?: DocumentStatus[]
  sort?: SortKey
  limit?: number
  offset?: number
}

export const documentsApi = {
  list: (params: ListDocumentsParams = {}) => {
    const query = new URLSearchParams()
    if (params.q) query.set('q', params.q)
    if (params.collectionId) query.set('collection_id', params.collectionId)
    params.tags?.forEach((t) => query.append('tag', t))
    if (params.readingStatus) query.set('reading_status', params.readingStatus)
    if (params.bookmarked !== undefined) query.set('bookmarked', String(params.bookmarked))
    params.status?.forEach((s) => query.append('status', s))
    if (params.sort) query.set('sort', params.sort)
    query.set('limit', String(params.limit ?? 100))
    if (params.offset) query.set('offset', String(params.offset))
    return request<Page<DocumentSummary>>(`/documents?${query}`)
  },
  stats: () => request<LibraryStats>('/documents/stats'),
  get: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  structure: (id: string) => request<DocumentStructure>(`/documents/${id}/structure`),
  versions: (id: string) => request<DocumentVersion[]>(`/documents/${id}/versions`),
  upload: (file: File, onProgress: (fraction: number) => void, signal?: AbortSignal) => {
    const form = new FormData()
    form.append('files', file)
    return uploadWithProgress<UploadResponse>('/documents', form, onProgress, signal)
  },
  importPapers: (refs: string[]) =>
    request<UploadResponse>('/documents/import', { method: 'POST', body: { refs } }),
  importZip: (file: File, collectionName: string, onProgress: (fraction: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    const query = collectionName.trim() ? `?collection_name=${encodeURIComponent(collectionName.trim())}` : ''
    return uploadWithProgress<ZipImportResponse>(`/documents/import/zip${query}`, form, onProgress)
  },
  fillFromDoi: (id: string, doi: string) =>
    request<DocumentDetail>(`/documents/${id}/metadata/doi`, { method: 'POST', body: { doi } }),
  addVersion: (id: string, file: File, onProgress: (fraction: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    return uploadWithProgress<DocumentSummary>(`/documents/${id}/versions`, form, onProgress)
  },
  updateMetadata: (id: string, body: MetadataUpdate) =>
    request<DocumentDetail>(`/documents/${id}/metadata`, { method: 'PATCH', body }),
  reprocess: (id: string) =>
    request<DocumentSummary>(`/documents/${id}/process`, { method: 'POST' }),
  resolveDuplicate: (id: string, action: 'keep_both' | 'merge_as_version' | 'delete') =>
    request<DocumentSummary | undefined>(`/documents/${id}/duplicate-resolution`, {
      method: 'POST',
      body: { action },
    }),
  remove: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),
  markOpened: (id: string) => request<void>(`/documents/${id}/opened`, { method: 'POST' }),
  reindex: (id: string) => request<DocumentSummary>(`/documents/${id}/reindex`, { method: 'POST' }),
  chunks: (id: string, limit = 200, offset = 0) =>
    request<Page<ChunkInfo>>(`/documents/${id}/chunks?limit=${limit}&offset=${offset}`),
  similar: (id: string) => request<SimilarPapers>(`/documents/${id}/similar`),
}

export const comparisonsApi = {
  create: (body: { document_ids: string[]; kind: ComparisonKind; force?: boolean }) =>
    request<Comparison>('/comparisons', { method: 'POST', body }),
  list: (params: { limit?: number; documentId?: string } = {}) => {
    const search = new URLSearchParams({ limit: String(params.limit ?? 20) })
    if (params.documentId) search.set('document_id', params.documentId)
    return request<ComparisonSummary[]>(`/comparisons?${search}`)
  },
  get: (id: string) => request<Comparison>(`/comparisons/${id}`),
  remove: (id: string) => request<void>(`/comparisons/${id}`, { method: 'DELETE' }),
}

export const collectionsApi = {
  list: () => request<Collection[]>('/collections'),
  get: (id: string) => request<CollectionDetail>(`/collections/${id}`),
  create: (body: { name: string; description?: string; kind?: CollectionKind; document_ids?: string[] }) =>
    request<Collection>('/collections', { method: 'POST', body }),
  update: (id: string, body: { name?: string; description?: string; kind?: CollectionKind }) =>
    request<Collection>(`/collections/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/collections/${id}`, { method: 'DELETE' }),
  addPapers: (id: string, documentIds: string[]) =>
    request<{ added: number; paper_count: number }>(`/collections/${id}/documents`, {
      method: 'POST',
      body: { document_ids: documentIds },
    }),
  removePaper: (id: string, documentId: string) =>
    request<void>(`/collections/${id}/documents/${documentId}`, { method: 'DELETE' }),
  exportUrl: (id: string, format: 'bibtex' | 'ris') => `/collections/${id}/export?format=${format}`,
}

export const tagsApi = {
  list: () => request<Tag[]>('/tags'),
  update: (id: string, body: { name?: string; color?: string }) =>
    request<Tag>(`/tags/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/tags/${id}`, { method: 'DELETE' }),
}

export const organizationApi = {
  get: (documentId: string) => request<DocumentOrganization>(`/documents/${documentId}/organization`),
  setTags: (documentId: string, names: string[]) =>
    request<DocumentOrganization>(`/documents/${documentId}/tags`, { method: 'PUT', body: { names } }),
  setReadingStatus: (documentId: string, status: ReadingStatus | null) =>
    request<DocumentOrganization>(`/documents/${documentId}/reading-status`, { method: 'PUT', body: { status } }),
  unbookmarkPaper: (documentId: string) =>
    request<void>(`/documents/${documentId}/bookmark`, { method: 'DELETE' }),
}

export const notesApi = {
  list: (params: { documentId?: string; collectionId?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.documentId) query.set('document_id', params.documentId)
    if (params.collectionId) query.set('collection_id', params.collectionId)
    return request<Note[]>(`/notes?${query}`)
  },
  create: (body: { content: string; document_id?: string; collection_id?: string; anchor?: Anchor }) =>
    request<Note>('/notes', { method: 'POST', body }),
  update: (id: string, content: string) => request<Note>(`/notes/${id}`, { method: 'PATCH', body: { content } }),
  remove: (id: string) => request<void>(`/notes/${id}`, { method: 'DELETE' }),
}

export const bookmarksApi = {
  list: (params: { documentId?: string; kinds?: BookmarkKind[] } = {}) => {
    const query = new URLSearchParams()
    if (params.documentId) query.set('document_id', params.documentId)
    params.kinds?.forEach((k) => query.append('kind', k))
    return request<Bookmark[]>(`/bookmarks?${query}`)
  },
  create: (body: { document_id: string; kind?: BookmarkKind; target?: Anchor; label?: string }) =>
    request<Bookmark>('/bookmarks', { method: 'POST', body }),
  remove: (id: string) => request<void>(`/bookmarks/${id}`, { method: 'DELETE' }),
}

export const summariesApi = {
  get: (documentId: string) => request<PaperSummary | null>(`/documents/${documentId}/summary`),
  generate: (documentId: string, force = false) =>
    request<PaperSummary>(`/documents/${documentId}/summary`, { method: 'POST', body: { force } }),
}

export const searchApi = {
  search: (body: SearchRequest, signal?: AbortSignal) =>
    request<SearchResponse>('/search', { method: 'POST', body, signal }),
  facets: () => request<SearchFacets>('/search/facets'),
}

export const chatApi = {
  list: (params: { documentId?: string; singlePaper?: boolean; limit?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.documentId) query.set('document_id', params.documentId)
    if (params.singlePaper) query.set('single_paper', 'true')
    if (params.limit) query.set('limit', String(params.limit))
    const suffix = query.size ? `?${query}` : ''
    return request<Page<Conversation>>(`/chat/conversations${suffix}`)
  },
  create: (body: { title?: string; document_ids?: string[]; collection_id?: string } = {}) =>
    request<Conversation>('/chat/conversations', { method: 'POST', body }),
  get: (id: string) => request<ConversationDetail>(`/chat/conversations/${id}`),
  rename: (id: string, title: string) =>
    request<Conversation>(`/chat/conversations/${id}`, { method: 'PATCH', body: { title } }),
  remove: (id: string) => request<void>(`/chat/conversations/${id}`, { method: 'DELETE' }),
  /** Ask a question; events (stage, evidence, tokens, verification) arrive as they happen. */
  ask: (id: string, content: string, onEvent: (event: ChatEvent) => void, signal?: AbortSignal, fresh = false) =>
    streamRequest<ChatEvent>(`/chat/conversations/${id}/messages`, { content, fresh }, onEvent, signal),
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  const text = query.toString()
  return text ? `?${text}` : ''
}

export const knowledgeApi = {
  graph: (params: { types?: string; limit?: number; focus?: string; includeMentions?: boolean } = {}) =>
    request<KnowledgeGraph>(
      `/graph${qs({ types: params.types, limit: params.limit, focus: params.focus, include_mentions: params.includeMentions })}`,
    ),
  neighbors: (node: string, params: { types?: string; includeMentions?: boolean; limit?: number } = {}) =>
    request<KnowledgeGraph>(
      `/graph/neighbors${qs({ node, types: params.types, include_mentions: params.includeMentions, limit: params.limit })}`,
    ),
  search: (q: string) => request<GraphNode[]>(`/graph/search${qs({ q })}`),
  path: (source: string, target: string) => request<KnowledgeGraph>(`/graph/path${qs({ source, target })}`),
  entities: (params: { type?: EntityType; q?: string; includeMentions?: boolean } = {}) =>
    request<EntityListItem[]>(`/entities${qs({ type: params.type, q: params.q, include_mentions: params.includeMentions })}`),
  entity: (id: string) => request<EntityDetail>(`/entities/${id}`),
  documentEntities: (id: string) => request<DocumentEntity[]>(`/documents/${id}/entities`),
  related: (id: string) => request<RelatedWork>(`/documents/${id}/related`),
  authors: (q?: string) => request<AuthorListItem[]>(`/authors${qs({ q })}`),
  author: (key: string) => request<AuthorDetail>(`/authors/${encodeURIComponent(key)}`),
  timeline: (filters: TimelineFilters = {}) =>
    request<Timeline>(
      `/timeline${qs({ topic: filters.topic, author: filters.author, venue: filters.venue, entity_id: filters.entityId })}`,
    ),
  topics: () => request<TopicsState>('/topics'),
  cluster: (body: { method: ClusterMethod; k?: number; min_cluster_size?: number }) =>
    request<TopicClustering>('/topics', { method: 'POST', body }),
}

const REPORT_PATHS: Record<ReportKind, string> = {
  review: '/literature-review',
  gaps: '/research-gaps',
  disagreements: '/contradictions',
  deep_research: '/deep-research',
}

export const reportsApi = {
  create: (kind: ReportKind, body: ReportRequest) =>
    request<Report>(REPORT_PATHS[kind], { method: 'POST', body: body as Record<string, unknown> }),
  list: (kind?: ReportKind) => request<ReportSummary[]>(`/reports${qs({ kind })}`),
  get: (id: string) => request<Report>(`/reports/${id}`),
  update: (id: string, body: { title?: string; sections?: { key: string; title?: string; text?: string }[] }) =>
    request<Report>(`/reports/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/reports/${id}`, { method: 'DELETE' }),
  export: (id: string, format: 'md' | 'docx' | 'pdf') =>
    request<Blob>(`/reports/${id}/export?format=${format}`, { blob: true }),
}

export const projectsApi = {
  list: () => request<ProjectSummary[]>('/projects'),
  create: (body: { idea: string; title?: string; collection_id?: string | null }) =>
    request<Project>('/projects', { method: 'POST', body }),
  get: (id: string) => request<Project>(`/projects/${id}`),
  update: (id: string, body: ProjectUpdate) =>
    request<Project>(`/projects/${id}`, { method: 'PATCH', body: body as Record<string, unknown> }),
  remove: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),
  suggest: (id: string, step: 'questions' | 'outline' | 'code') =>
    request<Project>(`/projects/${id}/suggest/${step}`, { method: 'POST' }),
  startReport: (id: string, step: 'background' | 'gaps') =>
    request<Project>(`/projects/${id}/reports/${step}`, { method: 'POST' }),
  methods: (id: string) => request<Project>(`/projects/${id}/methods`, { method: 'POST' }),
  planExperiments: (id: string, body: { deadline?: string; replace?: boolean }) =>
    request<Project>(`/projects/${id}/experiments`, { method: 'POST', body }),
  runAttentionExperiment: (id: string, scoreDivisor: number) =>
    request<ReferenceAttentionRun>(`/projects/${id}/experiments/run-attention`, {
      method: 'POST',
      body: { score_divisor: scoreDivisor },
    }),
  findClaimEvidence: (id: string, claim: string) =>
    request<ClaimEvidenceSearch>(`/projects/${id}/experiments/claim-evidence`, {
      method: 'POST',
      body: { claim },
    }),
  runClaimStressTest: (
    id: string,
    body: { claim: string; evidence_chunk_ids: string[]; dimensions: number[]; seed: number },
  ) => request<Project>(`/projects/${id}/experiments/claim-run`, { method: 'POST', body }),
  analyzeResults: (id: string, csv_text: string, filename: string) =>
    request<Project>(`/projects/${id}/experiments/analyze-results`, {
      method: 'POST',
      body: { csv_text, filename },
    }),
  createPaperRunMatch: (id: string, body: PaperRunMatchRequest) =>
    request<Project>(`/projects/${id}/experiments/paper-run-matches`, { method: 'POST', body: body as unknown as Record<string, unknown> }),
  deletePaperRunMatch: (id: string, matchId: string) =>
    request<Project>(`/projects/${id}/experiments/paper-run-matches/${matchId}`, { method: 'DELETE' }),
  analyzePredictions: (
    id: string,
    jsonl_text: string,
    filename: string,
    metric: string,
    higher_is_better: boolean,
  ) =>
    request<Project>(`/projects/${id}/experiments/analyze-predictions`, {
      method: 'POST',
      body: { jsonl_text, filename, metric, higher_is_better },
    }),
  export: (id: string, format: 'md' | 'docx' | 'latex' | 'code') =>
    request<Blob>(`/projects/${id}/export?format=${format}`, { blob: true }),
  guide: (id: string, step: GuideStep) => request<StepGuide>(`/projects/${id}/guide/${step}`),
  code: (id: string) => request<{ files: StarterFile[]; runs: ProjectCodeRun[] }>(`/projects/${id}/code`),
  saveCodeFile: (id: string, path: string, content: string) =>
    request<{ path: string; status: string }>(`/projects/${id}/code-file`, {
      method: 'PUT',
      body: { path, content },
    }),
  checkCodeFile: (id: string, path: string, content: string) =>
    request<CodeSyntaxCheck>(`/projects/${id}/code-file/check`, {
      method: 'POST',
      body: { path, content },
    }),
  runCode: (id: string) =>
    request<ProjectCodeRun>(`/projects/${id}/code/run`, { method: 'POST' }),
}

export const evaluationApi = {
  datasets: () => request<EvalDataset[]>('/evaluation/datasets'),
  createDataset: (body: { name: string; description?: string }) =>
    request<EvalDataset>('/evaluation/datasets', { method: 'POST', body }),
  dataset: (id: string) => request<EvalDataset>(`/evaluation/datasets/${id}`),
  deleteDataset: (id: string) => request<void>(`/evaluation/datasets/${id}`, { method: 'DELETE' }),
  items: (id: string) => request<EvalItem[]>(`/evaluation/datasets/${id}/items`),
  addItem: (id: string, body: { question: string; chunk_ids: string[]; reference_answer?: string }) =>
    request<EvalItem>(`/evaluation/datasets/${id}/items`, { method: 'POST', body }),
  updateItem: (id: string, body: { question?: string; status?: 'verified' | 'unverified' }) =>
    request<EvalItem>(`/evaluation/items/${id}`, { method: 'PATCH', body }),
  deleteItem: (id: string) => request<void>(`/evaluation/items/${id}`, { method: 'DELETE' }),
  generate: (id: string, count: number) =>
    request<EvalDataset>(`/evaluation/datasets/${id}/generate`, { method: 'POST', body: { count } }),
  runs: (datasetId?: string) => request<EvalRunSummary[]>(`/evaluation/runs${qs({ dataset_id: datasetId })}`),
  run: (id: string) => request<EvalRun>(`/evaluation/runs/${id}`),
  startRun: (datasetId: string, body: { name: string; kind: 'retrieval' | 'rag'; config: Partial<EvalRunConfig> }) =>
    request<EvalRun>(`/evaluation/datasets/${datasetId}/runs`, { method: 'POST', body: body as Record<string, unknown> }),
  deleteRun: (id: string) => request<void>(`/evaluation/runs/${id}`, { method: 'DELETE' }),
}

export const usageApi = {
  summary: (days: number) => request<UsageSummary>(`/usage?days=${days}`),
  performance: () => request<PerformanceSummary>('/usage/performance'),
}

export const demoApi = {
  samplePapers: () =>
    request<{ added: number; document_ids: string[]; collection_id: string }>('/demo/sample-papers', { method: 'POST' }),
}

export const watchesApi = {
  list: () => request<Watch[]>('/watches'),
  get: (id: string) => request<Watch>(`/watches/${id}`),
  create: (body: WatchCreate) =>
    request<Watch>('/watches', { method: 'POST', body: body as unknown as Record<string, unknown> }),
  update: (id: string, body: WatchUpdate) =>
    request<Watch>(`/watches/${id}`, {
      method: 'PATCH',
      body: body as unknown as Record<string, unknown>,
    }),
  remove: (id: string) => request<void>(`/watches/${id}`, { method: 'DELETE' }),
  runNow: (id: string) => request<WatchRun>(`/watches/${id}/run`, { method: 'POST' }),
  runs: (id: string, params: { limit?: number; offset?: number } = {}) =>
    request<Page<WatchRun>>(`/watches/${id}/runs${qs(params)}`),
  digest: (id: string, params: { limit?: number; offset?: number } = {}) =>
    request<Page<DigestEntry>>(`/watches/${id}/digest${qs(params)}`),
  importEntry: (watchId: string, entryId: string) =>
    request<DigestEntry>(`/watches/${watchId}/digest/${entryId}/import`, { method: 'POST' }),
}

export const notificationsApi = {
  list: (params: { limit?: number; offset?: number } = {}) =>
    request<Page<Notification>>(`/notifications${qs(params)}`),
  unreadCount: () => request<{ unread: number }>('/notifications/unread-count'),
  markRead: (id: string) => request<Notification>(`/notifications/${id}/read`, { method: 'POST' }),
  markAllRead: () => request<{ marked: number }>('/notifications/read-all', { method: 'POST' }),
}

export const publicApi = {
  getWatch: (id: string) => request<PublicWatch>(`/public/watches/${id}`),
  getDigest: (id: string, params: { limit?: number; offset?: number } = {}) =>
    request<Page<PublicDigestEntry>>(`/public/watches/${id}/digest${qs(params)}`),
}

export const webhooksApi = {
  list: () => request<Webhook[]>('/users/me/webhooks'),
  save: (platform: WebhookPlatform, url: string) =>
    request<Webhook>(`/users/me/webhooks/${platform}`, { method: 'PUT', body: { url } }),
  remove: (platform: WebhookPlatform) =>
    request<void>(`/users/me/webhooks/${platform}`, { method: 'DELETE' }),
  test: (platform: WebhookPlatform) =>
    request<{ ok: boolean }>(`/users/me/webhooks/${platform}/test`, { method: 'POST' }),
}
