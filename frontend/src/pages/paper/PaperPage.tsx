import { useEffect, useMemo, useRef, useState } from 'react'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useMutation } from '@tanstack/react-query'
import {
  ArrowLeft,
  Bookmark as BookmarkIcon,
  Copy,
  ExternalLink,
  GitCompareArrows,
  Lightbulb,
  Loader2,
  MessagesSquare,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { PaperChat } from '@/components/chat/PaperChat'
import type { OpenSource } from '@/components/chat/Sources'
import { MetadataDialog } from '@/components/documents/MetadataDialog'
import { BookmarksList } from '@/components/organization/Bookmarks'
import { CollectionMenu } from '@/components/organization/Collections'
import { NotesList } from '@/components/organization/Notes'
import { SaveActions } from '@/components/organization/SaveActions'
import { TagEditor } from '@/components/organization/Tags'
import { DocTypeLabel } from '@/components/documents/PaperViews'
import { StatusBadge } from '@/components/documents/StatusBadge'
import { DocumentReader, type ReaderTarget } from '@/components/reader/DocumentReader'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState, ProgressBar, Skeleton } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'
import { Sheet } from '@/components/ui/Sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { Tooltip } from '@/components/ui/Tooltip'
import { useDocument, useDocumentStructure } from '@/hooks/useDocuments'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import {
  useBookmarks,
  useDocumentOrganization,
  useNotes,
  useSetReadingStatus,
  useTogglePaperBookmark,
} from '@/hooks/useOrganization'
import { useGenerateSummary, useSummary } from '@/hooks/useSummary'
import { sourceLink } from '@/lib/chat'
import { compareLink, compareReason } from '@/lib/compare'
import { READING_STATUS } from '@/lib/organization'
import { stageLabel } from '@/lib/documents'
import { estimateRemaining, formatDuration } from '@/lib/format'
import { queryClient } from '@/lib/queryClient'
import { cn } from '@/lib/cn'
import { paragraphAt, type Box } from '@/lib/reader'
import { chatApi, documentsApi } from '@/services/api'
import { usePreferences } from '@/stores/preferences'
import type { Anchor, DocumentDetail, ReadingStatus } from '@/types/api'
import { EquationsTab, FiguresTab, ReferencesTab, TablesTab } from './ElementTabs'
import { PassagesTab, SimilarTab } from './IndexTabs'
import { OverviewTab } from './OverviewTab'
import { RelatedWork } from '@/components/knowledge/PaperKnowledge'
import { TransformerVisualizer } from './TransformerVisualizer'

const itemClass =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

function Header({
  doc,
  onEdit,
  chatOpen,
  chatLoading,
  onToggleChat,
  onSummarize,
  summarizing,
}: {
  doc: DocumentDetail
  onEdit: () => void
  chatOpen: boolean
  chatLoading: boolean
  onToggleChat: () => void
  onSummarize: () => void
  summarizing: boolean
}) {
  const organization = useDocumentOrganization(doc.id)
  const org = organization.data
  const toggleBookmark = useTogglePaperBookmark(doc.id)
  const setStatus = useSetReadingStatus(doc.id)
  const navigate = useNavigate()
  const versionInput = useRef<HTMLInputElement>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['documents'] })

  const reprocess = useMutation({
    mutationFn: () => documentsApi.reprocess(doc.id),
    onSuccess: () => {
      toast.success('Reprocessing started')
      void invalidate()
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => documentsApi.remove(doc.id),
    onSuccess: () => {
      toast.success('Paper deleted')
      void invalidate()
      navigate('/papers', { replace: true })
    },
    onError: (e) => toast.error(e.message),
  })
  const newVersion = useMutation({
    mutationFn: (file: File) => documentsApi.addVersion(doc.id, file, () => {}),
    onSuccess: () => {
      toast.success('New version uploaded. Processing has started.')
      void invalidate()
    },
    onError: (e) => toast.error(e.message),
  })
  const startResearchProject = () => {
    const query = new URLSearchParams({
      paper_id: doc.id,
      paper_title: doc.title,
      idea: `Build on “${doc.title}” by exploring its central method and proposing a small, testable extension.`,
    })
    navigate(`/projects?${query.toString()}`)
  }

  return (
    <header className="mb-6">
      <Link to="/papers" className="inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-3.5" /> Papers
      </Link>
      <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-h1 text-balance text-text">{doc.title}</h1>
          <p className="mt-1.5 text-body text-muted">
            {doc.authors_display || 'Authors not detected'}
            {doc.year && <span> · {doc.year}</span>}
            {doc.venue && <span> · {doc.venue}</span>}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <StatusBadge doc={doc} />
            <DocTypeLabel type={doc.doc_type} />
            {doc.version && doc.version_count > 1 && (
              <span className="text-caption text-subtle">v{doc.version.version_number}</span>
            )}
          </div>
          {org && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <select
                value={org.reading_status ?? ''}
                onChange={(e) => setStatus.mutate((e.target.value || null) as ReadingStatus | null)}
                aria-label="Reading status"
                className="h-6 rounded-full border border-border bg-surface px-2 text-caption text-text"
              >
                <option value="">Not started</option>
                {Object.entries(READING_STATUS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <TagEditor documentId={doc.id} tags={org.tags} />
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Tooltip content="Available once the paper is processed" disabled={doc.status === 'ready'}>
            <span>
              <Button
                variant={chatOpen ? 'primary' : 'secondary'}
                size="sm"
                onClick={onToggleChat}
                disabled={doc.status !== 'ready' || chatLoading}
                loading={chatLoading}
                aria-pressed={chatOpen}
              >
                {!chatLoading && <MessagesSquare className="size-4" aria-hidden />} Chat
              </Button>
            </span>
          </Tooltip>
          <Tooltip
            content={
              doc.status !== 'ready'
                ? 'Available once the paper is processed'
                : 'Problem, method, results and limitations, each cited to its page'
            }
          >
            <span>
              <Button
                variant="secondary"
                size="sm"
                onClick={onSummarize}
                disabled={doc.status !== 'ready'}
                loading={summarizing}
              >
                {!summarizing && <Sparkles className="size-4" aria-hidden />} Summarize
              </Button>
            </span>
          </Tooltip>
          <Tooltip content={compareReason(doc) ?? 'Compare this paper with others in your library'}>
            <span>
              <Button
                variant="secondary"
                size="sm"
                disabled={!!compareReason(doc)}
                onClick={() => navigate(compareLink([doc.id]))}
              >
                <GitCompareArrows className="size-4" aria-hidden /> Compare
              </Button>
            </span>
          </Tooltip>
          <Button variant="primary" size="sm" onClick={startResearchProject}>
            <Lightbulb className="size-4" aria-hidden /> Start research project
          </Button>
          {org && <CollectionMenu documentId={doc.id} memberOf={org.collections.map((c) => c.id)} />}
          <Tooltip content={org?.bookmarked ? 'Remove bookmark' : 'Bookmark this paper'}>
            <Button
              variant="secondary"
              size="icon-sm"
              aria-label={org?.bookmarked ? 'Remove bookmark' : 'Bookmark this paper'}
              aria-pressed={!!org?.bookmarked}
              disabled={!org}
              onClick={() => org && toggleBookmark.mutate(org.bookmarked)}
            >
              <BookmarkIcon className={cn('size-4', org?.bookmarked && 'fill-primary text-primary')} />
            </Button>
          </Tooltip>
          {doc.assets && (
            <Button variant="secondary" size="sm" onClick={() => window.open(doc.assets!.file, '_blank', 'noopener')}>
              <ExternalLink className="size-4" aria-hidden /> Original
            </Button>
          )}
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <Button variant="secondary" size="icon-sm" aria-label="More actions">
                <MoreHorizontal className="size-4" />
              </Button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content
                align="end"
                sideOffset={6}
                className="z-50 w-56 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
              >
                <Dropdown.Item className={itemClass} onSelect={onEdit} disabled={!doc.metadata}>
                  <Pencil className="size-4 text-muted" /> Edit details
                </Dropdown.Item>
                <Dropdown.Item className={itemClass} onSelect={() => versionInput.current?.click()}>
                  <Upload className="size-4 text-muted" /> Upload new version
                </Dropdown.Item>
                <Dropdown.Item
                  className={itemClass}
                  onSelect={() => reprocess.mutate()}
                  disabled={doc.status === 'queued' || doc.status === 'processing'}
                >
                  <RefreshCw className="size-4 text-muted" /> Reprocess
                </Dropdown.Item>
                <Dropdown.Item
                  className={itemClass}
                  onSelect={() => {
                    void navigator.clipboard?.writeText(window.location.href)
                    toast.success('Link copied')
                  }}
                >
                  <Copy className="size-4 text-muted" /> Copy link
                </Dropdown.Item>
                <Dropdown.Separator className="my-1 h-px bg-border" />
                <Dropdown.Item className={`${itemClass} text-error`} onSelect={() => setConfirmDelete(true)}>
                  <Trash2 className="size-4" /> Delete paper
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
          <input
            ref={versionInput}
            type="file"
            className="sr-only"
            aria-label="Choose new version file"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) newVersion.mutate(file)
              e.target.value = ''
            }}
          />
        </div>
      </div>
      <Dialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this paper?"
        description="The file, its extracted content and all versions will be permanently removed."
      >
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => remove.mutate()} loading={remove.isPending}>
            Delete
          </Button>
        </div>
      </Dialog>
    </header>
  )
}

function DuplicateBanner({ doc }: { doc: DocumentDetail }) {
  const navigate = useNavigate()
  const resolve = useMutation({
    mutationFn: (action: 'keep_both' | 'merge_as_version' | 'delete') =>
      documentsApi.resolveDuplicate(doc.id, action),
    onSuccess: (result, action) => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
      if (action === 'keep_both') toast.success('Kept as a separate paper')
      if (action === 'delete') {
        toast.success('Duplicate deleted')
        navigate(`/papers/${doc.duplicate_of!.document_id}`, { replace: true })
      }
      if (action === 'merge_as_version' && result) {
        toast.success('Merged as a new version')
        navigate(`/papers/${result.id}`, { replace: true })
      }
    },
    onError: (e) => toast.error(e.message),
  })
  if (!doc.duplicate_of) return null
  const phrasing = {
    exact_duplicate: 'is an exact copy of',
    probable_duplicate: 'is probably the same paper as',
    possible_duplicate: 'might be the same paper as',
  }[doc.duplicate_of.kind]
  return (
    <div className="mb-6 flex flex-col gap-3 rounded-lg border border-info/30 bg-info-soft p-4 sm:flex-row sm:items-center">
      <p className="flex-1 text-small text-text">
        This upload {phrasing}{' '}
        <Link to={`/papers/${doc.duplicate_of.document_id}`} className="font-medium text-primary hover:underline">
          {doc.duplicate_of.title}
        </Link>
        . What would you like to do?
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => resolve.mutate('keep_both')} disabled={resolve.isPending}>
          Keep both
        </Button>
        <Button size="sm" variant="secondary" onClick={() => resolve.mutate('merge_as_version')} disabled={resolve.isPending}>
          Save as new version
        </Button>
        <Button size="sm" variant="ghost" onClick={() => resolve.mutate('delete')} disabled={resolve.isPending}>
          Delete this copy
        </Button>
      </div>
    </div>
  )
}

function ProcessingPanel({ doc }: { doc: DocumentDetail }) {
  const retry = useMutation({
    mutationFn: () => documentsApi.reprocess(doc.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
    onError: (e) => toast.error(e.message),
  })
  if (doc.status === 'failed') {
    return (
      <ErrorState
        title="We couldn't process this document."
        error={{ message: doc.error_message }}
        onRetry={() => retry.mutate()}
      />
    )
  }
  const processing = doc.processing
  const eta = processing ? estimateRemaining(processing.started_at, processing.progress) : null
  return (
    <div className="rounded-lg border border-border bg-surface p-6" aria-live="polite">
      <div className="flex items-center gap-3">
        <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
        <div>
          <p className="font-medium text-text">Processing paper…</p>
          <p className="text-small text-muted">
            {processing?.stage_detail ?? stageLabel(processing?.stage)}
            {eta && ` · about ${formatDuration(eta)} remaining`}
          </p>
        </div>
      </div>
      <ProgressBar className="mt-4" value={processing?.progress ?? 0} label="Processing progress" />
      <ol className="mt-5 grid gap-2 text-small sm:grid-cols-4">
        {['Extracting text', 'Detecting structure', 'Indexing for search', 'Ready'].map((step, i) => {
          const reached = (processing?.progress ?? 0) >= [0, 0.5, 0.62, 1][i]
          return (
            <li key={step} className={reached ? 'text-text' : 'text-subtle'}>
              <span className="mr-1.5 tabular-nums">{i + 1}.</span>
              {step}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function PaperSkeleton() {
  return (
    <PageContainer width="wide">
      <Skeleton className="h-4 w-16" />
      <Skeleton className="mt-4 h-8 w-2/3" />
      <Skeleton className="mt-3 h-4 w-1/3" />
      <Skeleton className="mt-10 h-10 w-full" />
      <Skeleton className="mt-6 h-64 w-full" />
    </PageContainer>
  )
}

export function PaperPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const document = useDocument(id)
  const doc = document.data
  const ready = doc?.status === 'ready'
  const structure = useDocumentStructure(id, ready)
  const summary = useSummary(id, ready)
  const generateSummary = useGenerateSummary(id)
  const [editing, setEditing] = useState(false)
  const [target, setTarget] = useState<ReaderTarget | null>(null)
  const [explainQuestion, setExplainQuestion] = useState<string | null>(null)
  const [explainNonce, setExplainNonce] = useState(0)
  const tab = params.get('tab') ?? 'overview'
  const location = useLocation()
  const navigate = useNavigate()
  const showAdvanced = usePreferences((s) => s.showAdvanced)
  const hasTransformerArchitecture = /attention is all you need|transformer/i.test(doc?.title ?? '')

  useEffect(() => {
    if (id) void documentsApi.markOpened(id).catch(() => {})
  }, [id])

  // Deep links: ?tab=paper&page=3&char=1234 (search results and chat citations use these).
  // Applied once, when the structure first arrives.
  const [deepLinkApplied, setDeepLinkApplied] = useState(false)
  if (structure.data && !deepLinkApplied) {
    setDeepLinkApplied(true)
    const page = Number(params.get('page'))
    const char = params.get('char')
    if (page || char !== null) {
      const paragraph = char !== null ? paragraphAt(structure.data.sections, Number(char)) : null
      // In-app links (search results, later citations) pass the passage's exact boxes, which
      // also covers captions and tables that aren't paragraphs; shared URLs fall back to char.
      const exact = (location.state as { boxes?: Box[] } | null)?.boxes
      setTarget({
        page: exact?.[0]?.[0] ?? paragraph?.page_start ?? page,
        boxes: exact?.length ? exact : paragraph?.boxes,
        charStart: paragraph?.char_start,
        nonce: 0,
      })
    }
  }

  const setTab = (value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('tab', value)
        return next
      },
      { replace: true },
    )

  const notes = useNotes({ documentId: id })
  const bookmarks = useBookmarks({ documentId: id })
  const marks = useMemo(
    () =>
      [...(notes.data ?? []).map((n) => n.anchor), ...(bookmarks.data ?? []).map((b) => b.target)]
        .filter((a): a is Anchor => !!a && (a.char_start !== undefined || !!a.boxes?.length))
        .map((a) => ({ boxes: a.boxes, charStart: a.char_start })),
    [notes.data, bookmarks.data],
  )
  const openAnchor = (anchor: Anchor | null | undefined) =>
    anchor?.page && openInReader(anchor.page, anchor.boxes)
  const notesCount = (notes.data?.length ?? 0) + (bookmarks.data?.filter((b) => b.kind !== 'paper').length ?? 0)

  const openInReader = (page: number, boxes?: Box[]) => {
    setTab('paper')
    setTarget((previous) => ({ page, boxes, nonce: (previous?.nonce ?? 0) + 1 }))
  }

  // Split view: ?chat=<conversation id> (or "new") opens the assistant next to the reader.
  const chatParam = params.get('chat')
  const chatOpen = chatParam !== null
  const large = useMediaQuery('(min-width: 1024px)')
  const setChat = (value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value === null) next.delete('chat')
        else next.set('chat', value)
        return next
      },
      { replace: true },
    )
  const explainPassage = (paragraph: { text: string; page_start: number }, sectionTitle: string) => {
    const section = sectionTitle ? `Section: ${sectionTitle}. ` : ''
    setExplainQuestion(
      `Explain this selected passage from “${doc?.title ?? 'the paper'}” in depth. ${section}Page ${paragraph.page_start}.\n\nPassage:\n“${paragraph.text.slice(0, 3000)}”\n\nBreak it down sentence by sentence. Define technical terms and symbols in plain language, explain the intuition and how the claims connect to the paper's method, and distinguish what the passage says from any helpful analogy. Ground the explanation in this paper, cite relevant pages, and say clearly when the paper does not provide enough detail.`,
    )
    setExplainNonce((nonce) => nonce + 1)
    setTab('paper')
    setChat('new')
  }
  const [openingChat, setOpeningChat] = useState(false)
  const toggleChat = async () => {
    if (chatOpen) return setChat(null)
    // Continue the most recent chat about this paper, if there is one. Resolved before the
    // panel opens: switching the conversation after it opened raced with "New chat" and
    // with questions sent meanwhile (which then went to the wrong conversation).
    setOpeningChat(true)
    const recent = await chatApi.list({ documentId: id, singlePaper: true, limit: 1 }).catch(() => null)
    setOpeningChat(false)
    setChat(recent?.items[0]?.id ?? 'new')
  }
  const openSource: OpenSource = (item) => {
    if (item.document.id !== id) return navigate(sourceLink(item), { state: { boxes: item.boxes } })
    if (!large) setChat(null) // the sheet covers the reader on small screens
    openInReader(item.page_start, item.boxes)
  }

  // "Summarize": show the summary on the Overview tab, writing it first if there's none yet.
  const summarize = () => {
    setTab('overview')
    const current = summary.data
    if (!current || current.status === 'failed') generateSummary.mutate(false)
    window.requestAnimationFrame(() =>
      window.document.getElementById('ai-summary')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
    )
  }

  if (document.isPending) return <PaperSkeleton />
  if (document.isError || !doc)
    return (
      <PageContainer>
        <ErrorState error={document.error} title="We couldn't open this paper" onRetry={() => document.refetch()} />
      </PageContainer>
    )

  const s = structure.data
  const count = (kind: string) => s?.elements.filter((e) => e.kind === kind).length
  const pageTemplate = doc.assets?.page_template ?? null

  return (
    <PageContainer width="wide" className={cn(chatOpen && large && 'max-w-[110rem]')}>
      <Header
        doc={doc}
        onEdit={() => setEditing(true)}
        chatOpen={chatOpen}
        chatLoading={openingChat}
        onToggleChat={() => void toggleChat()}
        onSummarize={summarize}
        summarizing={generateSummary.isPending}
      />
      <DuplicateBanner doc={doc} />
      {!ready ? (
        <ProcessingPanel doc={doc} />
      ) : (
        <div className={cn(chatOpen && large && 'grid grid-cols-[minmax(0,1fr)_minmax(22rem,28rem)] items-start gap-6')}>
          <Tabs value={tab} onValueChange={setTab} className="min-w-0">
            <TabsList className="mb-6">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="paper">Paper</TabsTrigger>
              {hasTransformerArchitecture && <TabsTrigger value="model-map">Model map</TabsTrigger>}
              <TabsTrigger value="figures" count={count('figure')}>
                Figures
              </TabsTrigger>
              <TabsTrigger value="tables" count={count('table')}>
                Tables
              </TabsTrigger>
              {(count('equation') ?? 0) > 0 && (
                <TabsTrigger value="equations" count={count('equation')}>
                  Equations
                </TabsTrigger>
              )}
              <TabsTrigger value="references" count={s?.references.length}>
                References
              </TabsTrigger>
              <TabsTrigger value="notes" count={notesCount || undefined}>
                Notes
              </TabsTrigger>
              <TabsTrigger value="similar">Related</TabsTrigger>
              {showAdvanced && (
                <TabsTrigger value="passages" count={doc.version?.chunk_count || undefined}>
                  Passages
                </TabsTrigger>
              )}
            </TabsList>
            <TabsContent value="overview">
              <OverviewTab doc={doc} onOpenSource={openSource} />
            </TabsContent>
            {hasTransformerArchitecture && (
              <TabsContent value="model-map">
                <TransformerVisualizer />
              </TabsContent>
            )}
            <TabsContent value="notes">
              <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
                <section aria-labelledby="paper-notes">
                  <h2 id="paper-notes" className="mb-3 text-h3 text-text">
                    Notes
                  </h2>
                  <NotesList documentId={doc.id} onOpenAnchor={(note) => openAnchor(note.anchor)} />
                </section>
                <section aria-labelledby="paper-bookmarks">
                  <h2 id="paper-bookmarks" className="mb-3 text-h3 text-text">
                    Bookmarks
                  </h2>
                  <BookmarksList
                    documentId={doc.id}
                    kinds={['passage', 'table', 'figure', 'citation']}
                    onOpen={(bookmark) => openAnchor(bookmark.target)}
                    emptyHint="Click a passage in the reader, or use the bookmark buttons on figures, tables and chat citations."
                  />
                </section>
              </div>
            </TabsContent>
            <TabsContent value="similar">
              <div className="space-y-8">
                <RelatedWork documentId={doc.id} ready={doc.status === 'ready'} />
                <section>
                  <h2 className="mb-3 text-body font-semibold text-text">Similar by meaning</h2>
                  <SimilarTab doc={doc} />
                </section>
              </div>
            </TabsContent>
            <TabsContent value="passages">
              <PassagesTab doc={doc} onNavigate={openInReader} />
            </TabsContent>
            {structure.isError ? (
              <ErrorState error={structure.error} onRetry={() => structure.refetch()} />
            ) : !s ? (
              <Skeleton className="h-96 w-full" />
            ) : (
              <>
                <TabsContent value="paper" forceMount className="data-[state=inactive]:hidden">
                  <DocumentReader
                    structure={s}
                    pageTemplate={pageTemplate}
                    target={target}
                    marks={marks}
                    passageActions={({ paragraph, sectionTitle }) => (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => explainPassage(paragraph, sectionTitle)}
                          aria-label="Explain this passage alongside the paper"
                        >
                          <Sparkles className="size-3.5" aria-hidden /> Explain
                        </Button>
                        <SaveActions
                          documentId={doc.id}
                          kind={paragraph.kind === 'table' ? 'table' : 'passage'}
                          target={{
                            page: paragraph.page_start,
                            char_start: paragraph.char_start,
                            char_end: paragraph.char_end,
                            quote: paragraph.text.slice(0, 1200),
                            boxes: paragraph.boxes,
                            section_title: sectionTitle || undefined,
                          }}
                        />
                      </>
                    )}
                  />
                </TabsContent>
                <TabsContent value="figures">
                  <FiguresTab structure={s} pageTemplate={pageTemplate} onNavigate={openInReader} documentId={doc.id} />
                </TabsContent>
                <TabsContent value="tables">
                  <TablesTab structure={s} onNavigate={openInReader} documentId={doc.id} />
                </TabsContent>
                <TabsContent value="equations">
                  <EquationsTab structure={s} onNavigate={openInReader} />
                </TabsContent>
                <TabsContent value="references">
                  <ReferencesTab references={s.references} />
                </TabsContent>
              </>
            )}
          </Tabs>
          {chatOpen && large && (
            <aside
              aria-label="AI assistant"
              className="sticky top-[4.5rem] h-[calc(100dvh-5.5rem)] overflow-hidden rounded-lg border border-border bg-surface"
            >
              <PaperChat
                documentId={doc.id}
                conversationId={chatParam === 'new' ? null : chatParam}
                onConversation={(conversation) => setChat(conversation ?? 'new')}
                onOpen={openSource}
                onClose={() => {
                  setChat(null)
                  setExplainQuestion(null)
                }}
                initialQuestion={explainQuestion}
                initialQuestionKey={explainNonce}
              />
            </aside>
          )}
        </div>
      )}
      {ready && !large && (
        <Sheet
          open={chatOpen}
          onOpenChange={(open) => !open && setChat(null)}
          title="Ask about this paper"
          className="w-[min(32rem,100vw)]"
          bare
        >
          <PaperChat
            documentId={doc.id}
            conversationId={chatParam === 'new' || chatParam === null ? null : chatParam}
            onConversation={(conversation) => setChat(conversation ?? 'new')}
            onOpen={openSource}
            onClose={() => {
              setChat(null)
              setExplainQuestion(null)
            }}
            initialQuestion={explainQuestion}
            initialQuestionKey={explainNonce}
          />
        </Sheet>
      )}
      {editing && <MetadataDialog doc={doc} open={editing} onOpenChange={setEditing} />}
    </PageContainer>
  )
}
