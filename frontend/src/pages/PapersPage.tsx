import { useState, type DragEvent } from 'react'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useMutation } from '@tanstack/react-query'
import {
  BookOpen,
  Bookmark as BookmarkIcon,
  FolderOpen,
  FolderPlus,
  GitCompareArrows,
  LayoutGrid,
  List,
  Plus,
  Search,
  Upload,
  UploadCloud,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { CollectionDialog } from '@/components/organization/Collections'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { PaperGrid, PaperGridSkeleton, PaperTable, type Selection } from '@/components/documents/PaperViews'
import { ArxivImportButton } from '@/components/documents/ArxivImport'
import { ZipImportButton } from '@/components/documents/ZipImport'
import { SamplePapersButton } from '@/components/documents/SamplePapersButton'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { Tooltip } from '@/components/ui/Tooltip'
import { useDebounced } from '@/hooks/useDebounced'
import { useDocuments, useLibraryStats } from '@/hooks/useDocuments'
import { refreshOrganization, useCollections, useTags } from '@/hooks/useOrganization'
import { cn } from '@/lib/cn'
import { useUploads } from '@/stores/uploads'
import { MAX_COMPARE, compareLink, compareReason } from '@/lib/compare'
import { READING_STATUS } from '@/lib/organization'
import { collectionsApi } from '@/services/api'
import type { Collection, DocumentStatus, DocumentSummary, ReadingStatus, SortKey } from '@/types/api'

const SORTS: { value: SortKey; label: string }[] = [
  { value: 'recent', label: 'Recently added' },
  { value: 'opened', label: 'Recently opened' },
  { value: 'published', label: 'Publication date' },
  { value: 'title', label: 'Title' },
]

const MAX_SELECTED = 50

const FILTER_SELECT =
  'h-8 max-w-48 rounded-md border border-border bg-surface px-2 text-small text-text hover:border-border-strong'

/** Add the selected papers to a collection (or a new one). */
function AddToCollection({ documentIds, onDone }: { documentIds: string[]; onDone: () => void }) {
  const collections = useCollections()
  const [creating, setCreating] = useState(false)
  const add = useMutation({
    mutationFn: (collection: Collection) => collectionsApi.addPapers(collection.id, documentIds),
    onSuccess: (result, collection) => {
      toast.success(
        result.added
          ? `Added ${result.added} paper${result.added === 1 ? '' : 's'} to “${collection.name}”`
          : `Already in “${collection.name}”`,
      )
      refreshOrganization()
      onDone()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <Button variant="secondary" size="sm">
            <FolderPlus className="size-4" aria-hidden /> Add to collection
          </Button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content
            side="top"
            align="center"
            sideOffset={8}
            className="z-50 max-h-72 w-60 overflow-y-auto rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
          >
            {(collections.data ?? []).map((c) => (
              <Dropdown.Item key={c.id} className={MENU_ITEM} onSelect={() => add.mutate(c)}>
                <FolderOpen className="size-4 text-muted" /> <span className="truncate">{c.name}</span>
              </Dropdown.Item>
            ))}
            {collections.data?.length ? <Dropdown.Separator className="my-1 h-px bg-border" /> : null}
            <Dropdown.Item className={MENU_ITEM} onSelect={() => setCreating(true)}>
              <Plus className="size-4 text-muted" /> New collection…
            </Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
      {creating && (
        <CollectionDialog open={creating} onOpenChange={setCreating} documentIds={documentIds} onSaved={onDone} />
      )}
    </>
  )
}

const MENU_ITEM =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

const FILTERS: { value: string; label: string; statuses?: DocumentStatus[] }[] = [
  { value: 'all', label: 'All' },
  { value: 'ready', label: 'Ready', statuses: ['ready'] },
  { value: 'processing', label: 'Processing', statuses: ['queued', 'processing'] },
  { value: 'failed', label: 'Failed', statuses: ['failed'] },
]

function readView(): 'grid' | 'list' {
  try {
    return localStorage.getItem('ri-papers-view') === 'list' ? 'list' : 'grid'
  } catch {
    return 'grid'
  }
}

export function PapersPage() {
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') ?? '')
  const [view, setView] = useState<'grid' | 'list'>(readView)
  const [dragging, setDragging] = useState(false)
  const sort = (params.get('sort') as SortKey) || 'recent'
  const filter = params.get('status') ?? 'all'
  const debouncedQuery = useDebounced(query.trim())
  const openUpload = useUploads((s) => s.setDialogOpen)
  const addFiles = useUploads((s) => s.add)

  const statuses = FILTERS.find((f) => f.value === filter)?.statuses
  const collectionId = params.get('collection') ?? undefined
  const tag = params.get('tag') ?? undefined
  const reading = (params.get('reading') as ReadingStatus | 'none' | null) ?? undefined
  const saved = params.get('saved') === '1' || undefined
  const documents = useDocuments({
    q: debouncedQuery || undefined,
    sort,
    status: statuses,
    collectionId,
    tags: tag ? [tag] : undefined,
    readingStatus: reading,
    bookmarked: saved,
  })
  const collections = useCollections()
  const tags = useTags()
  const stats = useLibraryStats()

  const setParam = (key: string, value: string, fallback: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value === fallback) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true },
    )

  const changeView = (next: 'grid' | 'list') => {
    setView(next)
    try {
      localStorage.setItem('ri-papers-view', next)
    } catch {
      /* per-viewer convenience only */
    }
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const files = Array.from(event.dataTransfer.files)
    if (files.length) {
      addFiles(files)
      openUpload(true)
    }
  }

  // Papers picked for comparison (kept across searches and filters until cleared).
  const navigate = useNavigate()
  const [picked, setPicked] = useState<DocumentSummary[]>([])
  const selection: Selection = {
    selected: picked.map((d) => d.id),
    toggle: (doc) =>
      setPicked((current) =>
        current.some((d) => d.id === doc.id) ? current.filter((d) => d.id !== doc.id) : [...current, doc],
      ),
    reason: () => (picked.length >= MAX_SELECTED ? `Up to ${MAX_SELECTED} papers at a time` : null),
  }

  const notComparable = picked.find((d) => compareReason(d))
  const compareProblem =
    picked.length < 2
      ? 'Pick at least 2 papers to compare'
      : picked.length > MAX_COMPARE
        ? `Comparisons take up to ${MAX_COMPARE} papers`
        : notComparable
          ? `“${notComparable.title}”: ${compareReason(notComparable)}`
          : null

  const libraryEmpty = stats.data?.total === 0
  const items = documents.data?.items ?? []

  return (
    <div
      className="relative min-h-full"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault()
          setDragging(true)
        }
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragging(false)
      }}
      onDrop={onDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-3 z-20 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-primary-soft/80 backdrop-blur-sm">
          <div className="text-center">
            <UploadCloud className="mx-auto size-10 text-primary" />
            <p className="mt-2 text-h3 text-primary">Drop to upload</p>
          </div>
        </div>
      )}
      <PageContainer width="wide">
        <PageHeader
          title="Papers"
          description={
            stats.data && stats.data.total > 0
              ? `${stats.data.total} paper${stats.data.total === 1 ? '' : 's'} in your library${
                  stats.data.processing ? ` · ${stats.data.processing} processing` : ''
                }`
              : 'Upload, organize and read your research papers.'
          }
          actions={
            <>
              <ArxivImportButton />
              <ZipImportButton />
              <Button onClick={() => openUpload(true)}>
                <Upload className="size-4" aria-hidden /> Upload papers
              </Button>
            </>
          }
        />

        {libraryEmpty ? (
          <div className="rounded-lg border border-dashed border-border-strong bg-surface">
            <EmptyState
              icon={BookOpen}
              title="Your research library is empty."
              description="Upload your first paper to start building your research workspace. You can drop files anywhere on this page."
              actions={
                <>
                  <Button onClick={() => openUpload(true)}>Upload Paper</Button>
                  <ArxivImportButton />
                  <ZipImportButton />
                  <SamplePapersButton />
                </>
              }
            />
          </div>
        ) : (
          <>
            <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center">
              <div className="relative md:w-80">
                <Search
                  className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
                  aria-hidden
                />
                <Input
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value)
                    setParam('q', e.target.value, '')
                  }}
                  placeholder="Filter by title or author"
                  aria-label="Filter papers by title or author"
                  className="h-9 pl-9"
                />
                {query && (
                  <button
                    onClick={() => {
                      setQuery('')
                      setParam('q', '', '')
                    }}
                    aria-label="Clear filter"
                    className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-subtle hover:text-text"
                  >
                    <X className="size-3.5" />
                  </button>
                )}
              </div>
              <div
                className="flex gap-1 overflow-x-auto"
                role="radiogroup"
                aria-label="Filter by status"
              >
                {FILTERS.map((f) => (
                  <button
                    key={f.value}
                    role="radio"
                    aria-checked={filter === f.value}
                    onClick={() => setParam('status', f.value, 'all')}
                    className={cn(
                      'h-8 rounded-md px-3 text-small whitespace-nowrap transition-colors',
                      filter === f.value
                        ? 'bg-surface-muted font-medium text-text'
                        : 'text-muted hover:text-text',
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2 md:ml-auto">
                <label className="sr-only" htmlFor="sort">
                  Sort papers
                </label>
                <select
                  id="sort"
                  value={sort}
                  onChange={(e) => setParam('sort', e.target.value, 'recent')}
                  className="h-9 rounded-md border border-border bg-surface px-2.5 text-small text-text hover:border-border-strong"
                >
                  {SORTS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
                <div className="flex rounded-md border border-border bg-surface p-0.5">
                  {(
                    [
                      ['grid', LayoutGrid, 'Grid view'],
                      ['list', List, 'List view'],
                    ] as const
                  ).map(([value, Icon, label]) => (
                    <Tooltip key={value} content={label}>
                      <button
                        onClick={() => changeView(value)}
                        aria-label={label}
                        aria-pressed={view === value}
                        className={cn(
                          'rounded-sm p-1.5',
                          view === value ? 'bg-surface-muted text-text' : 'text-subtle hover:text-text',
                        )}
                      >
                        <Icon className="size-4" />
                      </button>
                    </Tooltip>
                  ))}
                </div>
              </div>
            </div>

            <div className="-mt-2 mb-5 flex flex-wrap items-center gap-2" aria-label="Organize filters">
              <select
                value={collectionId ?? ''}
                onChange={(e) => setParam('collection', e.target.value, '')}
                aria-label="Filter by collection"
                className={cn(FILTER_SELECT, collectionId && 'border-primary text-primary')}
              >
                <option value="">All collections</option>
                {(collections.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              <select
                value={tag ?? ''}
                onChange={(e) => setParam('tag', e.target.value, '')}
                aria-label="Filter by tag"
                className={cn(FILTER_SELECT, tag && 'border-primary text-primary')}
              >
                <option value="">All tags</option>
                {(tags.data ?? []).map((t) => (
                  <option key={t.id} value={t.name}>
                    #{t.name} ({t.paper_count})
                  </option>
                ))}
              </select>
              <select
                value={reading ?? ''}
                onChange={(e) => setParam('reading', e.target.value, '')}
                aria-label="Filter by reading status"
                className={cn(FILTER_SELECT, reading && 'border-primary text-primary')}
              >
                <option value="">Any reading status</option>
                {Object.entries(READING_STATUS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
                <option value="none">Not started</option>
              </select>
              <button
                type="button"
                aria-pressed={!!saved}
                onClick={() => setParam('saved', saved ? '' : '1', '')}
                className={cn(
                  'inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-small',
                  saved ? 'border-primary bg-primary-soft/40 text-primary' : 'border-border text-muted hover:text-text',
                )}
              >
                <BookmarkIcon className={cn('size-3.5', saved && 'fill-primary')} aria-hidden /> Bookmarked
              </button>
            </div>

            {documents.isPending ? (
              <PaperGridSkeleton />
            ) : documents.isError ? (
              <ErrorState error={documents.error} onRetry={() => documents.refetch()} />
            ) : items.length === 0 ? (
              <EmptyState
                icon={Search}
                title="No papers match"
                description="Try a different search, or clear the filters."
                actions={
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setQuery('')
                      setParams({}, { replace: true })
                    }}
                  >
                    Clear filters
                  </Button>
                }
              />
            ) : view === 'grid' ? (
              <PaperGrid docs={items} selection={selection} />
            ) : (
              <PaperTable docs={items} selection={selection} />
            )}
          </>
        )}
      </PageContainer>
      {picked.length > 0 && (
        <div
          role="region"
          aria-label="Selected papers"
          className="sticky bottom-4 z-30 mx-auto mt-6 flex w-fit max-w-[calc(100%-2rem)] items-center gap-3 rounded-lg border border-border bg-surface-elevated px-4 py-2.5 shadow-lg animate-fade-in"
        >
          <p className="text-small text-text">
            <span className="font-semibold tabular-nums">{picked.length}</span> selected
          </p>
          <Tooltip content={compareProblem ?? 'Compare these papers side by side'}>
            <span>
              <Button size="sm" disabled={!!compareProblem} onClick={() => navigate(compareLink(picked.map((d) => d.id)))}>
                <GitCompareArrows className="size-4" aria-hidden /> Compare selected
              </Button>
            </span>
          </Tooltip>
          <AddToCollection documentIds={picked.map((d) => d.id)} onDone={() => setPicked([])} />
          <Button variant="ghost" size="sm" onClick={() => setPicked([])}>
            Clear
          </Button>
        </div>
      )}
    </div>
  )
}
