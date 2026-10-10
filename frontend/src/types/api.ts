// Mirrors backend Pydantic schemas (app/schemas). Keep in sync when the API changes.

export type Theme = 'light' | 'dark' | 'system'
export type FontScale = 'sm' | 'md' | 'lg'

export interface UserPreferences {
  theme?: Theme
  font_scale?: FontScale
  sidebar_collapsed?: boolean
  onboarding_completed?: boolean
  default_search_mode?: 'hybrid' | 'semantic' | 'keyword'
  show_advanced?: boolean
}

export interface User {
  id: string
  email: string
  full_name: string
  is_admin: boolean
  preferences: UserPreferences
  created_at: string
  last_login_at: string | null
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_at: string
}

export interface RegisterResponse extends TokenResponse {
  user: User
}

export interface Session {
  id: string
  created_at: string
  expires_at: string
  user_agent: string
  ip_address: string
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface Job {
  id: string
  kind: string
  status: JobStatus
  stage: string
  stage_detail: string | null
  progress: number
  subject_type: string | null
  subject_id: string | null
  result: Record<string, unknown>
  error_message: string | null
  attempts: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface PublicConfig {
  app_name: string
  environment: string
  allow_registration: boolean
  max_upload_size_mb: number
  llm_provider: string
  llm_model: string
  embedding_model: string
  reranker_model: string
  local_only: boolean
  /** The server's model is a shared free one that each user opts in to. */
  free_tier: boolean
  /** Where to get the code to run your own copy; '' when not published. */
  download_url: string
}

export interface ApiErrorBody {
  code: string
  message: string
  hint?: string | null
  request_id?: string | null
  details?: { fields?: { field: string; message: string }[]; retry_after?: number } | null
}

// --- Documents (Phase 2) ---------------------------------------------------------

export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'failed'
export type DuplicateKind = 'exact_duplicate' | 'probable_duplicate' | 'possible_duplicate'
export type SortKey = 'recent' | 'opened' | 'published' | 'title'

export interface Author {
  name: string
  affiliation?: string | null
  email?: string | null
}

export interface ProcessingProgress {
  job_id: string
  status: JobStatus
  stage: string
  stage_detail: string | null
  progress: number
  started_at: string | null
  error_message: string | null
}

export interface DocumentAssets {
  thumbnail: string | null
  file: string
  page_template: string | null
}

export interface DocumentSummary {
  id: string
  title: string
  doc_type: 'pdf' | 'docx' | 'html' | 'markdown' | 'text'
  status: DocumentStatus
  authors_display: string
  year: number | null
  page_count: number | null
  original_filename: string
  error_message: string | null
  warnings: string[]
  duplicate_kind: DuplicateKind | null
  duplicate_of_id: string | null
  created_at: string
  updated_at: string
  last_opened_at: string | null
  index_status: 'pending' | 'indexed' | 'failed'
  index_error: string | null
  venue: string | null
  assets: DocumentAssets | null
  processing: ProcessingProgress | null
  reading_status: ReadingStatus | null
  tags: TagRef[]
  bookmarked: boolean
}

export interface Provenance {
  source: string
  confidence: 'high' | 'medium' | 'low'
}

export interface DocumentMetadata {
  title: string | null
  authors: Author[]
  affiliations: string[]
  abstract: string | null
  year: number | null
  publication_date: string | null
  venue: string | null
  doi: string | null
  arxiv_id: string | null
  keywords: string[]
  research_area: string | null
  provenance: Record<string, Provenance>
  user_corrected_fields: string[]
}

export interface DocumentVersion {
  id: string
  version_number: number
  original_filename: string
  file_size: number
  mime_type: string
  paginated: boolean
  page_count: number | null
  used_ocr: boolean
  ocr_pages: number[]
  parser: string | null
  processing_config: {
    pipeline_version?: string
    stats?: Record<string, number | number[] | Record<string, number>>
  }
  processed_at: string | null
  embedding_model: string | null
  embedding_dimension: number | null
  chunking_strategy: string | null
  chunk_count: number
  indexed_at: string | null
  created_at: string
}

export interface DocumentDetail extends DocumentSummary {
  metadata: DocumentMetadata | null
  version: DocumentVersion | null
  version_count: number
  duplicate_of: { kind: DuplicateKind; document_id: string; title: string } | null
}

export interface UploadResponse {
  items: DocumentSummary[]
  errors: { filename: string; message: string; hint: string | null }[]
}

export interface ZipImportResponse extends UploadResponse {
  skipped: { filename: string; reason: string }[]
  collection_id: string | null
}

export type MetadataUpdate = Partial<
  Pick<
    DocumentMetadata,
    | 'title'
    | 'authors'
    | 'abstract'
    | 'year'
    | 'publication_date'
    | 'venue'
    | 'doi'
    | 'arxiv_id'
    | 'keywords'
    | 'research_area'
  >
>

export interface Paragraph {
  text: string
  kind: 'text' | 'heading' | 'list_item' | 'code' | 'equation' | 'caption' | 'table'
  page_start: number
  page_end: number
  char_start: number
  char_end: number
  boxes: [number, number, number, number, number][]
}

export interface Section {
  id: string
  parent_id: string | null
  level: number
  kind: string
  title: string
  number: string | null
  page_start: number
  page_end: number
  paragraphs: Paragraph[]
}

export interface DocElement {
  id: string
  kind: 'figure' | 'table' | 'equation'
  label: string | null
  number: string | null
  caption: string | null
  page: number
  bbox: [number, number, number, number] | null
  content: { rows?: string[][]; text?: string }
  context: string | null
}

export interface DocReference {
  position: number
  raw_text: string
  title: string | null
  year: number | null
  doi: string | null
  arxiv_id: string | null
}

export interface PageInfo {
  number: number
  width: number | null
  height: number | null
  used_ocr: boolean
}

export interface DocumentStructure {
  version_id: string
  paginated: boolean
  pages: PageInfo[]
  sections: Section[]
  elements: DocElement[]
  references: DocReference[]
}

export interface LibraryStats {
  total: number
  ready: number
  processing: number
  failed: number
  duplicates: number
}

// --- Search index (Phase 3) -----------------------------------------------------------

export interface ChunkInfo {
  id: string
  chunk_index: number
  strategy: string
  kind: 'text' | 'table' | 'equation' | 'caption' | 'code'
  text: string
  context_header: string
  section_title: string
  section_kind: string
  page_start: number
  page_end: number
  char_start: number
  char_end: number
  token_count: number
  boxes: [number, number, number, number, number][]
}

export interface SimilarPapers {
  status: 'ok' | 'not_indexed' | 'no_other_papers'
  items: { document: DocumentSummary; score: number; reasons: string[] }[]
}

export interface AIStatus {
  embedding: { provider: string; model: string; remote: boolean; device: string }
  chunking: { strategy: string; chunk_size: number; chunk_overlap: number; contextual_headers: boolean }
  reranker: { provider: string; model: string | null; remote: boolean; candidates: number }
  retrieval: { sparse: string; candidates_per_retriever: number; rrf_k: number }
  vector_store: { backend: string; mode: 'embedded' | 'server' }
  loaded_models: { model: string; idle_seconds: number; load_seconds: number }[]
  llm: LLMStatus
  verifier: { provider: string; model: string | null }
  context: { token_budget: number; max_passages: number; min_relevance: number }
  local_only: boolean
}

// --- Search (Phase 4) ---------------------------------------------------------------------------

export type SearchMode = 'hybrid' | 'keyword' | 'semantic'

export type SearchFilters = {
  document_ids?: string[]
  year_from?: number
  year_to?: number
  authors?: string[]
  doc_types?: string[]
  section_kinds?: string[]
  include_references?: boolean
  collection_ids?: string[]
  tags?: string[]
}

export type SearchRequest = {
  query: string
  mode?: SearchMode
  filters?: SearchFilters
  limit?: number
  candidates?: number
  rerank?: boolean
  rerank_candidates?: number
  debug?: boolean
}

export interface SearchHit {
  rank: number
  chunk_id: string
  document: {
    id: string
    title: string
    authors_display: string
    year: number | null
    doc_type: string
    venue: string | null
  }
  text: string
  kind: ChunkInfo['kind']
  section_title: string
  section_kind: string
  page_start: number
  page_end: number
  char_start: number
  boxes: ChunkInfo['boxes']
  score: number
  score_kind: 'rerank' | 'rrf' | 'bm25' | 'fts' | 'cosine'
  matched_by: string[]
  retriever_ranks: Record<string, number>
  /** Rank before reranking (equals rank when not reranked). */
  fused_rank: number
  highlights: [number, number][]
  snippet: [number, number]
}

export interface TraceEntry {
  rank: number
  score: number
  chunk_id: string
  document_id?: string
  document_title?: string
  section_title?: string
  page?: number
  preview?: string
  missing?: boolean
  matched_terms?: Record<string, number> | null
  fused_rank?: number
  contributions?: Record<string, { rank: number; score: number; rrf: number }>
}

export interface SearchTrace {
  query: string
  query_terms: string[]
  fusion: { method: string; k: number } | null
  parameters: Record<string, unknown>
  stages: Record<string, TraceEntry[]>
}

export interface SearchResponse {
  query: string
  mode: SearchMode
  status: 'ok' | 'no_results' | 'empty_library'
  results: SearchHit[]
  retrievers: string[]
  /** Model that reordered the results, or null when not reranked. */
  reranker: string | null
  searched_papers: number
  warnings: string[]
  timings_ms: Record<string, number>
  trace: SearchTrace | null
}

export interface FacetValue {
  value: string
  count: number
}

export interface SearchFacets {
  papers: number
  indexed_papers: number
  year_min: number | null
  year_max: number | null
  doc_types: FacetValue[]
  authors: FacetValue[]
  section_kinds: FacetValue[]
  suggestions: string[]
  collections: (FacetValue & { label: string })[]
  tags: FacetValue[]
}

// --- Research chat (Phase 6) ---------------------------------------------------------------------

export interface LLMStatus {
  provider: string
  model: string
  remote: boolean
  ready: boolean
  /**
   * 'user': the model this user chose in Settings → AI; 'server': the server's default;
   * 'free': the site's shared free model, which they chose; 'none': the site has a free
   * model but they haven't chosen anything yet, so no model is in effect.
   */
  source?: 'user' | 'server' | 'free' | 'none'
  label?: string
  /** Who hosts the free shared model (text is sent there). */
  host?: string
  key_hint?: string
  problem?: string
  hint?: string
  installed?: string[]
}

// --- Each user's own model (Settings → AI) --------------------------------------------------------

export interface ModelPreset {
  id: string
  label: string
  provider: 'openai' | 'ollama'
  base_url: string
  keys_url: string
  note: string
  local: boolean
  needs_key: boolean
  /** Whether this server allows it (local models only on a self-hosted install). */
  available: boolean
}

export interface SavedModelChoice {
  preset: string
  label: string
  model: string
  base_url: string
  has_key: boolean
  key_hint: string
  updated_at: string
}

/** The site's shared free model: slower, with a daily allowance, hosted by a third party. */
export interface FreeTier {
  label: string
  model: string
  /** Who receives the questions and passages. */
  host: string
  chosen: boolean
  daily_limit: number
  used_today: number
  remaining_today: number
  resets_at: string
}

export interface ModelChoiceView {
  choice: SavedModelChoice | null
  server_default: { provider: string; model: string }
  /** null on a server without a free shared model. */
  free_tier: FreeTier | null
  download_url: string
  options: { presets: ModelPreset[]; allow_user_api_keys: boolean; allow_local_models: boolean }
  status: LLMStatus
}

export type ModelChoiceRequest = {
  /** A provider id, or 'free' for the site's shared free model. */
  preset: string
  model: string
  base_url?: string
  /** Omit to keep the key already saved for this provider. */
  api_key?: string
}

export interface ConnectionTest {
  ok: boolean
  models: string[]
  message: string
}

export interface Conversation {
  id: string
  title: string
  scope: 'library' | 'papers'
  document_ids: string[]
  collection_id?: string | null
  created_at: string
  updated_at: string
  last_message_at: string | null
}

export type SupportStatus = 'supported' | 'partial' | 'unsupported' | 'insufficient' | 'unverified'

export interface ClaimCheck {
  text: string
  citations: number[]
  status: 'supported' | 'partial' | 'unsupported' | 'uncited'
  entailment: number
  best_passage: number | null
  /** Supported by this passage although the claim's own citations don't support it
   *  (missing or wrong citation). */
  found_in?: number | null
  note?: string
}

export interface Verification {
  status: SupportStatus
  label: string
  explanation: string
  verifier: string
  claims: ClaimCheck[]
}

export interface QueryAnalysis {
  intent: string
  intent_cue: string | null
  entities: string[]
  year_from: number | null
  year_to: number | null
  temporal_phrase: string | null
  follow_up: boolean
  about_the_paper?: boolean
  retrieval_query: string
  notes: string[]
}

/** A passage the model was given, numbered as it is cited ([1], [2], ...). */
export interface EvidenceItem {
  number: number
  chunk_id: string | null
  document: { id: string | null; title: string; year: number | null; authors_display?: string }
  section_title: string
  page_start: number
  page_end: number
  char_start: number
  boxes: ChunkInfo['boxes']
  quote: string
  score: number
  cited?: boolean
  support_status?: string | null
}

export interface ContextDecision {
  chunk_id: string
  document_title: string
  section_title: string
  page: number
  score: number
  outcome: 'used' | 'dropped'
  reason: string
}

export interface RetrievalTraceData {
  query?: QueryAnalysis
  search?: {
    status: string
    retrievers: string[]
    reranker: string | null
    searched_papers: number
    warnings: string[]
    timings_ms: Record<string, number>
  }
  context?: { tokens: number; decisions: ContextDecision[] }
}

export interface CitationRecord {
  number: number
  chunk_id: string | null
  document_id: string | null
  document_title: string
  year: number | null
  section_title: string
  page_start: number
  page_end: number
  char_start: number
  quote: string
  boxes: ChunkInfo['boxes']
  score: number
  cited: boolean
  support_status: string | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: 'complete' | 'stopped' | 'error'
  error: string | null
  support: Verification | null
  retrieval_trace: RetrievalTraceData | null
  generation_config: Record<string, unknown> | null
  input_tokens: number
  output_tokens: number
  latency_ms: number | null
  created_at: string
  citations: CitationRecord[]
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[]
}

export type ChatStage = 'understanding' | 'searching' | 'reading' | 'reusing' | 'writing' | 'verifying'

/** An earlier answer reused for a near-identical question (Phase 14 answer cache). */
export interface ReusedFrom {
  message_id: string
  conversation_id: string
  question: string
  asked_at: string
  similarity: number
}

export type ChatEvent =
  | { type: 'status'; stage: ChatStage; detail: string }
  | { type: 'query'; analysis: QueryAnalysis }
  | { type: 'evidence'; items: EvidenceItem[]; reranker: string | null }
  | { type: 'token'; text: string }
  | { type: 'answer'; text: string; cited: number[]; invalid_citations: number[] }
  | ({ type: 'verification' } & Verification)
  | ({ type: 'reused' } & ReusedFrom)
  | {
      type: 'done'
      message_id: string
      usage: { input_tokens?: number; output_tokens?: number }
      timings_ms: Record<string, number>
    }
  | { type: 'error'; message: string; hint: string | null }

// --- Paper summaries (Phase 7) ------------------------------------------------------------------

export type SummaryFieldKey =
  | 'problem'
  | 'motivation'
  | 'method'
  | 'architecture'
  | 'dataset'
  | 'experiments'
  | 'results'
  | 'limitations'
  | 'future_work'
  | 'contribution'
  | 'takeaway'

export interface SummarySection {
  key: SummaryFieldKey
  title: string
  /** Markdown with [n] citations, or "Not reported." */
  text: string
  citations: number[]
  invalid_citations: number[]
  status: 'supported' | 'partial' | 'unsupported' | 'unverified' | 'not_reported'
  label: string
  explanation: string
  claims: ClaimCheck[]
}

export interface SummarySupport {
  status: SupportStatus
  label: string
  explanation: string
  verifier: string
  statements: number
  /** Titles of the fields the paper's passages don't cover. */
  not_reported: string[]
}

export interface PaperSummary {
  id: string
  document_id: string
  version_id: string
  status: 'queued' | 'running' | 'ready' | 'failed'
  sections: SummarySection[]
  /** The numbered passages the sections cite (same shape as chat sources). */
  sources: (EvidenceItem & { reason?: string; group?: string })[]
  support: SummarySupport | null
  generation_config: Record<string, unknown> & { llm_model?: string; verifier?: string | null }
  trace: { groups?: { group: string; fields: string[]; latency_ms?: number; note?: string }[] }
  input_tokens: number
  output_tokens: number
  latency_ms: number | null
  error_message: string | null
  error_hint: string | null
  progress: { stage: string; detail: string | null; progress: number } | null
  /** Why the summary no longer matches the paper or the configuration. */
  stale: string | null
  /** The last ready summary, while this one is being written or after it failed. */
  previous: PaperSummary | null
  created_at: string
  updated_at: string
}

// --- Comparisons (Phase 8) ----------------------------------------------------------------------

export type ComparisonKind = 'papers' | 'methodology'

export interface ComparisonColumn {
  document_id: string
  version_id: string
  /** A, B, C… — how the overview refers to the papers. */
  letter: string
  title: string
  year: number | null
  authors_display: string
  extraction_id: string | null
  deleted: boolean
}

export interface ComparisonCell {
  document_id: string
  letter: string
  /** Markdown with [n] citations into `sources`, or "Not reported." */
  text: string
  citations: number[]
  status: SummarySection['status']
  label: string
  explanation: string
  claims: ClaimCheck[]
}

export interface ComparisonRow {
  key: string
  title: string
  /** From the cells' words: similar / different; partial = some papers don't report it. */
  agreement: 'similar' | 'different' | 'partial' | 'none'
  cells: ComparisonCell[]
}

export interface ComparisonSummary {
  id: string
  title: string
  kind: ComparisonKind
  status: 'queued' | 'running' | 'ready' | 'failed'
  columns: ComparisonColumn[]
  created_at: string
  updated_at: string
}

export interface Comparison extends ComparisonSummary {
  rows: ComparisonRow[]
  sources: (EvidenceItem & { letter?: string })[]
  overview: Omit<SummarySection, 'key' | 'title' | 'invalid_citations'> | null
  support: SummarySupport | null
  generation_config: Record<string, unknown> & { llm_model?: string }
  trace: { papers?: { document_id: string; cached: boolean }[] }
  input_tokens: number
  output_tokens: number
  latency_ms: number | null
  error_message: string | null
  error_hint: string | null
  progress: { stage: string; detail: string | null; progress: number } | null
  stale: string | null
}

// --- Organization (Phase 9) ---------------------------------------------------------------------

export type ReadingStatus = 'to_read' | 'reading' | 'done'
export type CollectionKind = 'project' | 'review' | 'thesis' | 'course' | 'other'
export type BookmarkKind = 'paper' | 'passage' | 'table' | 'figure' | 'citation'

export interface TagRef {
  id: string
  name: string
  color: string | null
}

export interface Tag extends TagRef {
  paper_count: number
}

export interface Collection {
  id: string
  name: string
  description: string
  kind: CollectionKind
  paper_count: number
  note_count: number
  created_at: string
  updated_at: string
}

export interface CollectionDetail extends Collection {
  documents: DocumentSummary[]
}

export interface DocumentOrganization {
  tags: TagRef[]
  reading_status: ReadingStatus | null
  bookmarked: boolean
  collections: { id: string; name: string }[]
}

/** Where a note or bookmark points; page/quote/boxes are snapshots that survive reprocessing. */
export interface Anchor {
  type?: 'paper' | 'page' | 'passage' | 'citation'
  page?: number
  char_start?: number
  char_end?: number
  quote?: string
  boxes?: [number, number, number, number, number][]
  section_title?: string
  chunk_id?: string
  element_id?: string
  conversation_id?: string
  message_id?: string
  citation_number?: number
}

export interface Note {
  id: string
  content: string
  document_id: string | null
  collection_id: string | null
  anchor: Anchor | null
  document_title: string | null
  created_at: string
  updated_at: string
}

export interface Bookmark {
  id: string
  document_id: string
  kind: BookmarkKind
  target: Anchor
  label: string
  document_title: string | null
  document_year: number | null
  created_at: string
}

// --- Knowledge (Phase 10) --------------------------------------------------------------------

export type EntityType = 'dataset' | 'model' | 'method' | 'metric' | 'task'
export type NodeType = 'paper' | 'author' | 'institution' | 'topic' | EntityType
export type EntityRelation = 'proposes' | 'uses' | 'mentions'

export interface GraphNode {
  id: string
  type: NodeType
  label: string
  importance: number
  degree: number
  hidden_neighbors: number
  data: Record<string, unknown> & { ref?: string; year?: number | null; papers?: number; authors?: string }
}

export interface GraphEdge {
  source: string
  target: string
  relation: string
  weight: number
}

export interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  hidden: Partial<Record<NodeType, number>>
  total_nodes: number
  total_edges: number
  paper_count: number
  entity_status: { entities?: number; links?: number; citations?: number; authors?: number; topics?: number }
}

export interface EntityEvidence {
  quote: string
  page: number
  section_kind: string
  section_id?: string | null
  paragraph_index?: number | null
  surface: string
}

export interface EntityBrief {
  id: string
  type: EntityType
  name: string
}

export interface PaperBrief {
  id: string
  title: string
  year: number | null
  venue: string | null
  authors: string
  topic: { id: number; name: string } | null
}

export interface EntityListItem extends EntityBrief {
  aliases: string[]
  source: 'catalog' | 'discovered'
  paper_count: number
  mention_count: number
  proposed_by: number
  first_year: number | null
  last_year: number | null
  has_info: boolean
}

export interface EntityPaper extends PaperBrief {
  relation: EntityRelation
  mentions: number
  variants: string[]
  evidence: EntityEvidence[]
}

export interface EntityDetail extends EntityBrief {
  aliases: string[]
  source: 'catalog' | 'discovered'
  info: Record<string, string>
  papers: EntityPaper[]
  related: (EntityBrief & { shared_papers: number })[]
  years: { year: number; papers: number }[]
}

export interface DocumentEntity extends EntityBrief {
  relation: EntityRelation
  mentions: number
  variants: string[]
  evidence: EntityEvidence[]
  paper_count: number
}

export interface AuthorListItem {
  key: string
  name: string
  paper_count: number
  institutions: string[]
  first_year: number | null
  last_year: number | null
}

export interface AuthorDetail {
  key: string
  name: string
  spellings: string[]
  paper_count: number
  papers: PaperBrief[]
  coauthors: { key: string; name: string; shared_papers: number }[]
  institutions: string[]
  topics: { name: string; papers: number }[]
  keywords: string[]
  entities: (EntityBrief & { papers: number })[]
  years: { year: number; papers: number }[]
}

export interface TimelinePaper extends PaperBrief {
  proposes: EntityBrief[]
  uses: EntityBrief[]
}

export interface Timeline {
  years: { year: number; papers: TimelinePaper[]; first_seen: EntityBrief[] }[]
  undated: TimelinePaper[]
  paper_count: number
  filters: {
    topics: { id: number; name: string; size: number }[]
    authors: { key: string; name: string; papers: number }[]
    venues: { name: string; papers: number }[]
    methods: (EntityBrief & { papers: number })[]
  }
}

export interface TimelineFilters {
  topic?: number
  author?: string
  venue?: string
  entityId?: string
}

export interface RelatedWork {
  cites: (PaperBrief & { match: string; reference: string })[]
  cited_by: (PaperBrief & { match: string; reference: string })[]
  shared_entities: (PaperBrief & { shared: Partial<Record<EntityType, string[]>>; score: number })[]
  same_authors: (PaperBrief & { shared_authors: string[] })[]
  topic: { id: number; name: string } | null
}

export type ClusterMethod = 'auto' | 'kmeans' | 'agglomerative' | 'hdbscan'

export interface TopicCluster {
  id: number
  name: string
  name_source: 'terms' | 'model'
  terms: string[]
  entities: string[]
  document_ids: string[]
  size: number
}

export interface TopicClustering {
  id: string
  method: ClusterMethod
  params: { k?: number | null; min_cluster_size?: number | null }
  embedding_model: string
  naming_status: 'pending' | 'done' | 'fallback'
  naming_model: string | null
  error_message: string | null
  created_at: string
  clusters: TopicCluster[]
  points: { document_id: string; title: string; x: number; y: number; cluster: number }[]
  quality: {
    silhouette?: number | null
    noise?: number
    chosen_k?: number
    k_scores?: Record<string, number | null>
    min_cluster_size?: number
    variance_2d?: number
  }
  excluded: { document_id: string; reason: string }[]
  paper_count: number
  stale: string | null
}

export interface TopicsState {
  clustering: TopicClustering | null
  searchable_papers: number
}

// --- Reports (Phase 11) ----------------------------------------------------------------------

export type ReportKind = 'review' | 'gaps' | 'disagreements' | 'deep_research'
export type ReportStatus = 'queued' | 'running' | 'ready' | 'failed'
export type ReportDepth = 'brief' | 'standard' | 'detailed'

export interface ReportClaim {
  text: string
  citations: number[]
  status: string
  entailment: number
  found_in?: number | null
  /** "Citation corrected / added by the checker" */
  note?: string
}

export interface ReportGap {
  id: string
  kind: 'stated' | 'combination' | 'disagreement'
  origin: 'Stated by the authors' | 'System-generated synthesis'
  title: string
  text: string
  papers: { id: string; title: string; year: number | null }[]
  statements: { document: { id: string; title: string; year: number | null }; field: string; text: string; citations: number[] }[]
}

export interface ReportDisagreement {
  claim_a: { document: { id: string; title: string; year: number | null }; text: string; field: string; citations: number[] }
  claim_b: { document: { id: string; title: string; year: number | null }; text: string; field: string; citations: number[] }
  shared: string[]
  differences: Record<string, { a: string[]; b: string[] }>
  score: number
  detector: 'nli' | 'polarity'
  label: string
  note: string
}

export interface ReportSection {
  key: string
  title: string
  kind: 'text' | 'answer' | 'chronology' | 'table' | 'gaps' | 'disagreements' | 'open'
  text: string
  citations: number[]
  claims: ReportClaim[]
  status: string
  label: string
  origin: 'generated' | 'derived' | 'scaffold'
  edited?: boolean
  removed?: { text: string; reason: string }[]
  data?: {
    papers?: { id: string; title: string; year: number | null }[]
    terms?: string[]
    name_source?: string
    rows?: {
      year?: number | null
      document: { id: string; title: string; year?: number | null }
      proposes?: string[]
      approach?: string
      datasets?: string[]
      metrics?: string[]
      result?: string
      citations?: number[]
    }[]
    items?: ReportDisagreement[]
    gaps?: ReportGap[]
    directions?: { text: string; based_on: string[]; papers: { id: string; title: string; year: number | null }[]; origin: string }[]
    questions?: string[]
  }
}

export interface ReportSummary {
  id: string
  kind: ReportKind
  title: string
  query: string
  status: ReportStatus
  document_ids: string[]
  collection_id: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  edited_at: string | null
}

export interface DeepResearchStep {
  step: number
  action: 'plan' | 'search' | 'answer' | 'refine' | 'synthesize' | 'stopped'
  elapsed_ms: number
  tokens_so_far: number
  subquestions?: string[]
  query?: string
  question?: string
  found?: number
  kept?: number
  papers?: string[]
  status?: string
  cited?: number[]
  reason?: string
  new_passages?: number
}

export interface Report extends ReportSummary {
  params: { document_ids?: string[]; collection_id?: string | null; depth?: ReportDepth; max_steps?: number; token_budget?: number; timeout_seconds?: number }
  sections: ReportSection[]
  sources: (Omit<EvidenceItem, 'score'> & { score?: number })[]
  support: { status: string; statements: number; counts: Record<string, number>; verifier: string; explanation: string } | null
  trace: {
    steps?: DeepResearchStep[]
    tools?: string[]
    limits?: { max_steps: number; token_budget: number; timeout_seconds: number }
    used?: { steps: number; tokens: number; seconds: number }
    stopped?: string | null
    papers?: { how: string; query?: string; rule?: string }
    skipped?: { document_id: string; reason: string }[]
    summaries_written?: string[]
    error_hint?: string | null
  }
  generation_config: { llm_model?: string; verifier?: string | null; depth?: string }
  input_tokens: number
  output_tokens: number
  latency_ms: number | null
  progress: { stage: string; detail: string | null; progress: number } | null
  error_hint: string | null
}

export interface ReportRequest {
  topic?: string
  question?: string
  document_ids?: string[]
  collection_id?: string | null
  depth?: ReportDepth
  max_steps?: number
  token_budget?: number
  timeout_seconds?: number
}

// --- Research projects (Phase 12) ------------------------------------------------------------

export type ProjectStep = 'questions' | 'background' | 'gaps' | 'methods' | 'experiments' | 'outline'

export interface ProjectMethodSuggestion {
  entity_id: string
  name: string
  papers: { id: string; title: string; year: number | null }[]
  count: number
  proposed_by: number
  info: Record<string, string>
}

export interface ProjectExperiment {
  key: string
  kind: 'main' | 'ablation' | 'analysis' | 'custom'
  title: string
  goal: string
  setup: string
  metrics: string[]
  notes: string
}

export interface ProjectMilestone {
  title: string
  due: string
  done: boolean
}

export interface ProjectMethodsChoice {
  datasets: string[]
  baselines: string[]
  methods: string[]
  metrics: string[]
}

export interface ProjectSteps {
  questions: {
    status: 'idle' | 'running' | 'ready' | 'failed'
    suggestions: { text: string; citations: number[]; papers: string[]; status: string }[]
    sources: Report['sources']
    error: string | null
    note?: string
  }
  background: { report_id: string | null }
  gaps: { report_id: string | null; chosen: { id: string; title: string; text: string; origin: string } | null }
  methods: {
    suggestions: Partial<Record<EntityType, ProjectMethodSuggestion[]>>
    chosen: ProjectMethodsChoice
    paper_count?: number
  }
  experiments: { items: ProjectExperiment[]; milestones: ProjectMilestone[]; deadline: string | null }
  outline: {
    status: 'idle' | 'running' | 'ready' | 'failed'
    sections: ReportSection[]
    sources: Report['sources']
    error: string | null
  }
}

export type GuideStep = ProjectStep | 'code'

export interface StepGuide {
  step: GuideStep
  number: number
  of: number
  title: string
  why: string
  actions: { title: string; detail: string }[]
  expected: string
  checks: string[]
  pitfalls: string[]
  yours: string[]
  previous: GuideStep | null
  next: GuideStep | null
}

export interface StarterFile {
  path: string
  purpose: string
  content: string
}

export interface ProjectSummary {
  id: string
  title: string
  idea: string
  question: string
  collection_id: string | null
  created_at: string
  updated_at: string
}

export interface Project extends ProjectSummary {
  hypothesis: string
  steps: ProjectSteps
  completion: Record<ProjectStep, boolean>
  guidance?: {
    next_step: { step: ProjectStep | null; message: string }
    notes: string[]
  } | null
  reports: { background: ReportSummary | null; gaps: ReportSummary | null }
  progress: { stage: string; detail: string | null; progress: number } | null
}

export interface ProjectUpdate {
  title?: string
  idea?: string
  question?: string
  hypothesis?: string
  collection_id?: string | null
  gap?: ProjectSteps['gaps']['chosen'] | Record<string, never>
  methods?: ProjectMethodsChoice
  experiments?: ProjectExperiment[]
  milestones?: ProjectMilestone[]
  outline?: { key: string; text: string }[]
}

// --- Evaluation (Phase 13) ---------------------------------------------------------------------

export interface EvalDataset {
  id: string
  name: string
  description: string
  generation: { status?: 'running' | 'done' | 'failed'; requested?: number; created?: number; skipped?: number; error?: string | null }
  created_at: string
  updated_at: string
  verified: number
  unverified: number
  runs: number
}

export interface EvalEvidence {
  document_id: string
  version_id: string
  char_start: number
  char_end: number
  page: number
  quote: string
  title: string
}

export interface EvalItem {
  id: string
  dataset_id: string
  question: string
  expected: EvalEvidence[]
  reference_answer: string
  source: 'manual' | 'generated'
  status: 'verified' | 'unverified'
  created_at: string
}

export type EvalMode = 'keyword' | 'semantic' | 'hybrid'

export interface EvalRunConfig {
  mode: EvalMode
  rerank: boolean
  top_k?: number
  rerank_candidates?: number
  rrf_k?: number
  context_max_passages?: number
  index?: { papers: number; embedding_models: string[]; chunking_strategies: string[] }
  reranker?: string | null
  llm_model?: string | null
  verifier?: string | null
}

export interface EvalRunSummary {
  id: string
  dataset_id: string
  name: string
  kind: 'retrieval' | 'rag'
  config: EvalRunConfig
  status: 'queued' | 'running' | 'ready' | 'failed'
  metrics: Record<string, number | null>
  items_evaluated: number
  latency_ms: number | null
  error_message: string | null
  created_at: string
}

export interface EvalRun extends EvalRunSummary {
  per_item: {
    item_id: string
    question: string
    metrics: Record<string, number>
    top: { title: string; page: number; relevant: boolean }[]
    latency_ms: Record<string, number>
    answer?: string
  }[]
  progress: { stage: string; detail: string | null; progress: number } | null
}

// --- Usage & performance (Phase 14) ----------------------------------------------------------

export interface UsageGroup {
  calls: number
  errors: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  latency_p50_ms: number | null
  latency_p95_ms: number | null
  first_token_p50_ms: number | null
  feature?: string
  model?: string
}

export interface UsageSummary {
  days: number
  totals: {
    calls: number
    errors: number
    input_tokens: number
    output_tokens: number
    cost_usd: number
    estimated_calls: number
    latency_p50_ms: number | null
    latency_p95_ms: number | null
  }
  by_feature: UsageGroup[]
  by_model: UsageGroup[]
  by_day: { day: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number }[]
  pricing: {
    default: [number, number]
    models: Record<string, [number, number]>
    current_model: { model: string; input: number; output: number }
  }
}

export interface PerformanceSummary {
  stages: { key: string; label: string; count: number; mean_ms: number; p50_ms: number | null; p95_ms: number | null }[]
  caches: {
    name: string
    entries: number
    max_entries: number
    local_hits: number
    shared_hits: number
    misses: number
    hit_rate: number | null
    shared: boolean
  }[]
  since: string
}

/** One entry of the account's security activity (audit log). */
export interface ActivityEvent {
  id: string
  action: string
  resource_type: string | null
  resource_id: string | null
  ip_address: string
  created_at: string
}
