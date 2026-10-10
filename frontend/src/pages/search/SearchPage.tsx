import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  BookOpen,
  Loader2,
  Search,
  SearchX,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'
import { Sheet } from '@/components/ui/Sheet'
import { Tooltip } from '@/components/ui/Tooltip'
import { useDebounced } from '@/hooks/useDebounced'
import { cn } from '@/lib/cn'
import {
  LIMITS,
  SEARCH_MODES,
  activeFilterCount,
  groupByPaper,
  readSearchState,
  writeSearchState,
  type SearchState,
} from '@/lib/search'
import { documentsApi, searchApi } from '@/services/api'
import { useUploads } from '@/stores/uploads'
import type { SearchFacets, SearchResponse } from '@/types/api'
import { RetrievalTrace } from './RetrievalTrace'
import { SearchFiltersPanel } from './SearchFilters'
import { PaperResult } from './SearchResults'

const ADVANCED_KEY = 'ri-search-advanced'

function readAdvanced() {
  try {
    return localStorage.getItem(ADVANCED_KEY) === '1'
  } catch {
    return false
  }
}

function AdvancedOptions({
  state,
  update,
}: {
  state: SearchState
  update: (patch: Partial<SearchState>) => void
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border border-border bg-surface px-4 py-3">
      <div role="radiogroup" aria-label="Search mode" className="flex rounded-md border border-border p-0.5">
        {SEARCH_MODES.map((mode) => (
          <button
            type="button"
            key={mode.value}
            role="radio"
            aria-checked={state.mode === mode.value}
            title={mode.description}
            onClick={() => update({ mode: mode.value })}
            className={cn(
              'rounded-sm px-3 py-1 text-small transition-colors',
              state.mode === mode.value
                ? 'bg-primary-soft font-medium text-primary'
                : 'text-muted hover:text-text',
            )}
          >
            {mode.label}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-small text-muted">
        Results
        <select
          value={state.limit}
          onChange={(e) => update({ limit: Number(e.target.value) })}
          className="h-8 rounded-md border border-border bg-surface px-2 text-small text-text"
        >
          {LIMITS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <Tooltip content="Reorders retrieved passages using a more precise relevance model.">
        <label className="flex cursor-pointer items-center gap-2 text-small text-muted">
          <input
            type="checkbox"
            checked={state.rerank}
            onChange={(e) => update({ rerank: e.target.checked })}
            className="size-4 accent-[var(--primary)]"
          />
          Rerank results
        </label>
      </Tooltip>
      <label className="flex cursor-pointer items-center gap-2 text-small text-muted">
        <input
          type="checkbox"
          checked={state.debug}
          onChange={(e) => update({ debug: e.target.checked })}
          className="size-4 accent-[var(--primary)]"
        />
        Show how results were found
      </label>
      <p className="w-full text-caption text-subtle">
        {SEARCH_MODES.find((m) => m.value === state.mode)?.description}
      </p>
    </div>
  )
}

function PaperScopeChip({ id, onClear }: { id: string; onClear: () => void }) {
  const doc = useQuery({ queryKey: ['documents', 'detail', id], queryFn: () => documentsApi.get(id) })
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-surface py-1 pr-1 pl-3 text-small">
      <span className="text-muted">In</span>
      <span className="truncate font-medium text-text">{doc.data?.title ?? 'this paper'}</span>
      <button
        type="button"
        onClick={onClear}
        className="rounded-full p-0.5 text-muted hover:bg-surface-muted hover:text-text"
        aria-label="Search all papers"
      >
        <X className="size-3.5" />
      </button>
    </span>
  )
}

function Results({ response, fetching }: { response: SearchResponse; fetching: boolean }) {
  const groups = useMemo(() => groupByPaper(response.results), [response.results])
  const maxScore = response.results[0]?.score ?? 0
  return (
    <div className={cn('space-y-4 transition-opacity', fetching && 'opacity-60')}>
      {groups.map((group) => (
        <PaperResult key={group.document.id} group={group} maxScore={maxScore} />
      ))}
    </div>
  )
}

function Suggestions({ facets, onPick }: { facets?: SearchFacets; onPick: (q: string) => void }) {
  if (!facets?.suggestions.length) return null
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <span className="text-small text-muted">Try:</span>
      {facets.suggestions.map((suggestion) => (
        <button
          type="button"
          key={suggestion}
          onClick={() => onPick(suggestion)}
          className="rounded-full border border-border bg-surface px-3 py-1 text-small text-text hover:border-border-strong hover:bg-surface-muted"
        >
          {suggestion}
        </button>
      ))}
    </div>
  )
}

export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const state = useMemo(() => readSearchState(params), [params])
  const [input, setInput] = useState(state.query)
  const [advanced, setAdvanced] = useState(
    () =>
      readAdvanced() ||
      state.mode !== 'hybrid' ||
      state.debug ||
      state.limit !== 20 ||
      !state.rerank,
  )
  const [filtersOpen, setFiltersOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const openUpload = useUploads((s) => s.setDialogOpen)

  const update = (patch: Partial<SearchState>, replace = true) =>
    setParams(writeSearchState({ ...state, ...patch }), { replace })

  // URL → input (back/forward, ⌘K, suggestion chips), adjusted during render.
  const [syncedQuery, setSyncedQuery] = useState(state.query)
  if (state.query !== syncedQuery) {
    setSyncedQuery(state.query)
    setInput(state.query)
  }
  // Input → URL, as you type.
  const typed = useDebounced(input.trim(), 300)
  useEffect(() => {
    if (typed !== state.query && (typed.length >= 2 || typed === '')) update({ query: typed })
  }, [typed]) // eslint-disable-line react-hooks/exhaustive-deps

  // "/" focuses the search box when you're not already typing somewhere.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (event.key !== '/' || target.closest('input, textarea, select, [contenteditable]')) return
      event.preventDefault()
      inputRef.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const facets = useQuery({
    queryKey: ['search', 'facets'],
    queryFn: searchApi.facets,
    staleTime: 30_000,
  })
  const request = {
    query: state.query,
    mode: state.mode,
    filters: state.filters,
    limit: state.limit,
    debug: state.debug,
  }
  // Fused results first (tens of ms)…
  const fused = useQuery({
    queryKey: ['search', 'results', { ...state, rerank: false }],
    queryFn: ({ signal }) => searchApi.search({ ...request, rerank: false }, signal),
    enabled: state.query.length > 0,
    placeholderData: (previous) => previous,
    staleTime: 30_000,
    retry: false,
  })
  // …then the cross-encoder's order replaces them (about a second on CPU). Scores are cached
  // server-side, so refining or repeating a search is fast.
  const reranked = useQuery({
    queryKey: ['search', 'results', { ...state, rerank: true }],
    queryFn: ({ signal }) => searchApi.search(request, signal),
    enabled: state.query.length > 0 && state.rerank,
    staleTime: 30_000,
    retry: false,
  })
  const showReranked = state.rerank && reranked.isSuccess
  const search = showReranked ? reranked : fused
  const refining = state.rerank && reranked.isFetching && !showReranked && fused.isSuccess
  const fetching = fused.isFetching || reranked.isFetching

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const query = input.trim()
    if (query) update({ query }, false)
  }
  const toggleAdvanced = () => {
    const next = !advanced
    setAdvanced(next)
    try {
      localStorage.setItem(ADVANCED_KEY, next ? '1' : '0')
    } catch {
      /* per-viewer convenience only */
    }
  }

  const filterCount = activeFilterCount(state.filters)
  const paperScope = state.filters.document_ids?.[0]
  const response = search.data
  const libraryEmpty = facets.data?.papers === 0
  const nothingIndexed = facets.data && facets.data.papers > 0 && facets.data.indexed_papers === 0

  const filters = facets.data && (
    <SearchFiltersPanel
      facets={facets.data}
      filters={state.filters}
      onChange={(next) => update({ filters: next })}
    />
  )

  return (
    <PageContainer width="wide">
      <h1 className="sr-only">Search</h1>
      <form role="search" onSubmit={submit} className="mx-auto max-w-3xl">
        <div className="relative">
          <Search
            className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-subtle"
            aria-hidden
          />
          <input
            ref={inputRef}
            autoFocus
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search your research…"
            aria-label="Search your research"
            maxLength={500}
            className="h-14 w-full rounded-xl border border-border bg-surface pr-24 pl-12 text-body text-text shadow-sm placeholder:text-subtle hover:border-border-strong focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-primary/20 focus-visible:outline-none sm:text-lg [&::-webkit-search-cancel-button]:hidden"
          />
          <div className="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-1">
            {fetching && (
              <Loader2 className="size-4 animate-spin text-subtle" aria-label="Searching" />
            )}
            {input && (
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="Clear search"
                onClick={() => {
                  setInput('')
                  update({ query: '' })
                  inputRef.current?.focus()
                }}
              >
                <X className="size-4" />
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Advanced search options"
              aria-expanded={advanced}
              onClick={toggleAdvanced}
              className={cn(advanced && 'bg-surface-muted text-text')}
            >
              <SlidersHorizontal className="size-4" />
            </Button>
          </div>
        </div>
        {advanced && <AdvancedOptions state={state} update={update} />}
        {paperScope && (
          <div className="mt-3">
            <PaperScopeChip
              id={paperScope}
              onClear={() => update({ filters: { ...state.filters, document_ids: undefined } })}
            />
          </div>
        )}
        {!state.query && <Suggestions facets={facets.data} onPick={(q) => update({ query: q }, false)} />}
      </form>

      {libraryEmpty ? (
        <div className="mx-auto mt-10 max-w-3xl rounded-lg border border-dashed border-border-strong bg-surface">
          <EmptyState
            icon={BookOpen}
            title="Nothing to search yet."
            description="Upload papers and they become searchable as soon as they're processed."
            actions={<Button onClick={() => openUpload(true)}>Upload papers</Button>}
          />
        </div>
      ) : nothingIndexed ? (
        <div className="mx-auto mt-10 max-w-3xl">
          <EmptyState
            icon={Loader2}
            title="Your papers are being prepared for search."
            description="Papers appear in search once they've been split into passages and indexed. This usually takes under a minute per paper."
          />
        </div>
      ) : (
        <div className="mt-8 grid gap-8 lg:grid-cols-[15rem_minmax(0,1fr)]">
          <aside className="hidden lg:block" aria-label="Filters">
            <div className="sticky top-20">{filters ?? <Skeleton className="h-64 w-full" />}</div>
          </aside>

          <section aria-live="polite" aria-busy={fetching} className="min-w-0 space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                size="sm"
                className="lg:hidden"
                onClick={() => setFiltersOpen(true)}
              >
                <SlidersHorizontal className="size-4" aria-hidden /> Filters
                {filterCount > 0 && <Badge tone="primary">{filterCount}</Badge>}
              </Button>
              {response && state.query && (
                <p className="text-small text-muted">
                  {response.results.length > 0 ? (
                    <>
                      {response.results.length} passage{response.results.length === 1 ? '' : 's'} in{' '}
                      {groupByPaper(response.results).length} paper
                      {groupByPaper(response.results).length === 1 ? '' : 's'}
                    </>
                  ) : (
                    'No matches'
                  )}{' '}
                  · searched {response.searched_papers} paper{response.searched_papers === 1 ? '' : 's'} ·{' '}
                  {Math.round(response.timings_ms.total ?? 0)} ms
                  {response.reranker && (
                    <Tooltip content={`Reordered by ${response.reranker}`}>
                      <span className="ml-2 inline-flex align-middle">
                        <Badge tone="primary">Reranked</Badge>
                      </span>
                    </Tooltip>
                  )}
                </p>
              )}
              {refining && (
                <span className="inline-flex items-center gap-1.5 text-caption text-subtle">
                  <Loader2 className="size-3.5 animate-spin" aria-hidden /> Refining the order…
                </span>
              )}
            </div>

            {response?.warnings.map((warning) => (
              <div
                key={warning}
                role="status"
                className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-small text-text"
              >
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                {warning}
              </div>
            ))}

            {!state.query ? (
              <p className="py-10 text-center text-small text-muted">
                Search finds passages by their exact words and by their meaning, across every paper in
                your library.
              </p>
            ) : search.isError ? (
              <ErrorState
                error={search.error}
                title="Search didn't work"
                onRetry={() => search.refetch()}
              />
            ) : !response ? (
              <div className="space-y-4" aria-label="Loading results">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-40 w-full" />
                ))}
              </div>
            ) : response.status === 'empty_library' ? (
              <EmptyState
                icon={BookOpen}
                title="No searchable papers yet."
                description="Papers become searchable once they've been processed and indexed."
              />
            ) : response.results.length === 0 ? (
              <EmptyState
                icon={SearchX}
                title={`No passages match “${response.query}”.`}
                description={
                  filterCount > 0
                    ? 'Try removing some filters, or use different words.'
                    : state.mode === 'keyword'
                      ? 'Keyword search needs the exact words (or their forms). Try hybrid search to also match by meaning.'
                      : 'Try different or fewer words.'
                }
                actions={
                  filterCount > 0 ? (
                    <Button variant="secondary" onClick={() => update({ filters: {} })}>
                      Clear filters
                    </Button>
                  ) : state.mode === 'keyword' ? (
                    <Button variant="secondary" onClick={() => update({ mode: 'hybrid' })}>
                      Use hybrid search
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <Results response={response} fetching={fused.isFetching && fused.isPlaceholderData} />
            )}

            {response?.trace && state.debug && <RetrievalTrace response={response} />}
          </section>
        </div>
      )}

      <Sheet
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        title="Filters"
        footer={
          <Button className="w-full" onClick={() => setFiltersOpen(false)}>
            Show results
          </Button>
        }
      >
        {filters}
      </Sheet>
    </PageContainer>
  )
}
