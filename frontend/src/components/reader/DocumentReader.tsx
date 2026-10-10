import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  ListTree,
  Minus,
  Plus,
  ScanLine,
  Search,
  X,
} from 'lucide-react'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/cn'
import {
  buildToc,
  paragraphAtPoint,
  parseMarkdownTable,
  renderWidth,
  sectionTitles,
  searchParagraphs,
  type Box,
  type SearchHit,
  type TocNode,
} from '@/lib/reader'
import type { DocumentStructure, Paragraph } from '@/types/api'

export interface ReaderTarget {
  page: number
  boxes?: Box[]
  charStart?: number
  nonce: number // lets the same target be requested twice
}

export interface SelectedPassage {
  paragraph: Paragraph
  sectionTitle: string
}

interface ReaderProps {
  structure: DocumentStructure
  pageTemplate: string | null
  target?: ReaderTarget | null
  /** Click a paragraph to select it; these actions (note, bookmark…) are offered for it. */
  passageActions?: (passage: SelectedPassage) => ReactNode
  /** Passages that have notes or bookmarks, marked subtly in the text. */
  marks?: { boxes?: Box[]; charStart?: number }[]
}

const ZOOMS = [0.6, 0.75, 0.9, 1, 1.15, 1.3, 1.5, 1.75, 2]

function IconButton({
  label,
  onClick,
  children,
  active,
  disabled,
}: {
  label: string
  onClick: () => void
  children: ReactNode
  active?: boolean
  disabled?: boolean
}) {
  return (
    <Tooltip content={label}>
      <button
        onClick={onClick}
        aria-label={label}
        aria-pressed={active}
        disabled={disabled}
        className={cn(
          'rounded-md p-1.5 text-muted hover:bg-surface-muted hover:text-text disabled:opacity-40',
          active && 'bg-surface-muted text-text',
        )}
      >
        {children}
      </button>
    </Tooltip>
  )
}

function Toc({
  nodes,
  onSelect,
  activePage,
}: {
  nodes: TocNode[]
  onSelect: (node: TocNode) => void
  activePage: number
}) {
  const render = (list: TocNode[], depth: number): ReactNode => (
    <ul className={cn(depth > 0 && 'ml-3 border-l border-border pl-2')}>
      {list.map((node) => {
        const { section } = node
        const active = activePage >= section.page_start && activePage <= section.page_end
        return (
          <li key={section.id}>
            <button
              onClick={() => onSelect(node)}
              className={cn(
                'block w-full truncate rounded-sm px-2 py-1 text-left text-small hover:bg-surface-muted',
                active && depth === 0 ? 'font-medium text-text' : 'text-muted',
              )}
              title={section.title}
            >
              {section.number && <span className="mr-1.5 text-subtle">{section.number}</span>}
              {section.title}
            </button>
            {node.children.length > 0 && render(node.children, depth + 1)}
          </li>
        )
      })}
    </ul>
  )
  return nodes.length ? (
    render(nodes, 0)
  ) : (
    <p className="px-2 text-small text-muted">No sections were detected in this document.</p>
  )
}

function SearchPanel({
  hits,
  query,
  onSelect,
}: {
  hits: SearchHit[]
  query: string
  onSelect: (hit: SearchHit) => void
}) {
  if (query.trim().length < 2) return null
  return (
    <div className="absolute top-full right-0 z-30 mt-1 max-h-96 w-[min(28rem,90vw)] overflow-y-auto rounded-lg border border-border bg-surface-elevated p-1 shadow-lg">
      {hits.length === 0 ? (
        <p className="px-3 py-4 text-center text-small text-muted">No matches in this paper.</p>
      ) : (
        <ul>
          <li className="px-3 py-1.5 text-caption text-subtle">
            {hits.length}
            {hits.length === 50 ? '+' : ''} matches
          </li>
          {hits.map((hit, index) => (
            <li key={`${hit.paragraph.char_start}-${index}`}>
              <button
                onClick={() => onSelect(hit)}
                className="w-full rounded-md px-3 py-2 text-left hover:bg-surface-muted"
              >
                <span className="text-caption text-subtle">
                  {hit.sectionTitle} · page {hit.paragraph.page_start}
                </span>
                <span className="mt-0.5 line-clamp-2 block text-small text-text">
                  <Highlighted text={hit.snippet} query={query} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Highlighted({ text, query }: { text: string; query: string }) {
  const needle = query.trim()
  if (needle.length < 2) return <>{text}</>
  const parts = text.split(new RegExp(`(${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig'))
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === needle.toLowerCase() ? (
          <mark key={i} className="rounded-sm bg-warning-soft px-0.5 text-text">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  )
}

export function DocumentReader({ structure, pageTemplate, target, passageActions, marks = [] }: ReaderProps) {
  const [selected, setSelected] = useState<SelectedPassage | null>(null)
  const titles = useMemo(() => sectionTitles(structure.sections), [structure.sections])
  const markBoxes = useMemo(() => marks.flatMap((m) => m.boxes ?? []), [marks])
  const markedStarts = useMemo(
    () => new Set(marks.map((m) => m.charStart).filter((c): c is number => c !== undefined)),
    [marks],
  )
  const toc = useMemo(() => buildToc(structure.sections), [structure.sections])
  const [tocOpen, setTocOpen] = useState(() => window.innerWidth >= 1024)
  const [query, setQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [highlight, setHighlight] = useState<{ boxes: Box[]; charStart?: number } | null>(null)
  const hits = useMemo(() => searchParagraphs(structure.sections, query), [structure.sections, query])
  const scrollRef = useRef<HTMLDivElement>(null)
  const [zoomIndex, setZoomIndex] = useState(ZOOMS.indexOf(1))
  const [current, setCurrent] = useState(1)
  const [pageInput, setPageInput] = useState('1')
  const total = structure.pages.length
  const zoom = ZOOMS[zoomIndex]
  const onCurrentPage = useCallback((page: number) => {
    setCurrent(page)
    setPageInput(String(page))
  }, [])
  const goTo = (page: number) => pdfNavigate.current?.(page)

  const paginated = structure.paginated && pageTemplate !== null
  const focusParagraph = useCallback((paragraph: Paragraph) => {
    setHighlight({ boxes: paragraph.boxes, charStart: paragraph.char_start })
    return paragraph
  }, [])
  const selectParagraph = useCallback(
    (paragraph: Paragraph | null) => {
      if (!passageActions) return
      setSelected(paragraph ? { paragraph, sectionTitle: titles.get(paragraph.char_start) ?? '' } : null)
      if (paragraph) setHighlight({ boxes: paragraph.boxes, charStart: paragraph.char_start })
    },
    [passageActions, titles],
  )
  const onPageClick = useCallback(
    (page: number, x: number, y: number) => selectParagraph(paragraphAtPoint(structure.sections, page, x, y)),
    [selectParagraph, structure.sections],
  )

  const onSelectHit = (hit: SearchHit) => {
    focusParagraph(hit.paragraph)
    setSearchOpen(false)
    pdfNavigate.current?.(hit.paragraph.page_start, hit.paragraph.boxes)
    textNavigate.current?.(hit.paragraph.char_start)
  }
  const onSelectSection = (node: TocNode) => {
    const first = node.section.paragraphs[0]
    setHighlight(null)
    pdfNavigate.current?.(node.section.page_start, first?.boxes.slice(0, 1))
    textNavigate.current?.(first?.char_start ?? null, node.section.id)
    if (window.innerWidth < 1024) setTocOpen(false)
  }

  const pdfNavigate = useRef<((page: number, boxes?: Box[]) => void) | null>(null)
  const textNavigate = useRef<((charStart: number | null, sectionId?: string) => void) | null>(null)
  const registerPdfNavigate = useCallback((fn: (page: number, boxes?: Box[]) => void) => {
    pdfNavigate.current = fn
  }, [])
  const registerTextNavigate = useCallback(
    (fn: (charStart: number | null, sectionId?: string) => void) => {
      textNavigate.current = fn
    },
    [],
  )

  // A new navigation target (from figures, deep links, citations) resets the highlight.
  // Starts as null (not `target`): a deep link mounts the reader with a target already set,
  // and that first target must be highlighted too.
  const [seenTarget, setSeenTarget] = useState<ReaderTarget | null | undefined>(null)
  if (target !== seenTarget) {
    setSeenTarget(target)
    if (target) setHighlight({ boxes: target.boxes ?? [], charStart: target.charStart })
  }

  useEffect(() => {
    if (!target) return
    const boxes = target.boxes ?? []
    // Scrolling is a DOM side effect; wait a frame so newly mounted pages exist.
    requestAnimationFrame(() => {
      pdfNavigate.current?.(target.page, boxes)
      if (target.charStart !== undefined) textNavigate.current?.(target.charStart)
    })
  }, [target])

  return (
    <div className="flex h-[calc(100dvh-10.5rem)] min-h-[480px] flex-col overflow-hidden rounded-lg border border-border bg-surface">
      <div className="relative flex items-center gap-1 border-b border-border px-2 py-1.5">
        <IconButton label="Table of contents" onClick={() => setTocOpen((o) => !o)} active={tocOpen}>
          <ListTree className="size-4" />
        </IconButton>
        <div className="mx-1 h-5 w-px bg-border" />
        {paginated && (
          <div className="flex items-center gap-1">
            <IconButton label="Previous page" onClick={() => goTo(current - 1)} disabled={current <= 1}>
              <ChevronLeft className="size-4" />
            </IconButton>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                goTo(Number(pageInput) || 1)
              }}
              className="flex items-center gap-1 text-small text-muted"
            >
              <input
                value={pageInput}
                onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ''))}
                aria-label="Page number"
                className="h-7 w-10 rounded-md border border-border bg-surface text-center text-small text-text tabular-nums"
              />
              <span className="tabular-nums">/ {total}</span>
            </form>
            <IconButton label="Next page" onClick={() => goTo(current + 1)} disabled={current >= total}>
              <ChevronRight className="size-4" />
            </IconButton>
            <div className="mx-1 hidden h-5 w-px bg-border sm:block" />
            <div className="hidden items-center gap-1 sm:flex">
              <IconButton
                label="Zoom out"
                onClick={() => setZoomIndex((z) => Math.max(0, z - 1))}
                disabled={zoomIndex === 0}
              >
                <Minus className="size-4" />
              </IconButton>
              <span className="w-11 text-center text-caption text-muted tabular-nums">
                {Math.round(zoom * 100)}%
              </span>
              <IconButton
                label="Zoom in"
                onClick={() => setZoomIndex((z) => Math.min(ZOOMS.length - 1, z + 1))}
                disabled={zoomIndex === ZOOMS.length - 1}
              >
                <Plus className="size-4" />
              </IconButton>
              <IconButton label="Fit width" onClick={() => setZoomIndex(ZOOMS.indexOf(1))}>
                <ScanLine className="size-4" />
              </IconButton>
            </div>
          </div>
        )}
        <div className="relative ml-auto flex items-center">
          <Search className="pointer-events-none absolute left-2.5 size-3.5 text-subtle" aria-hidden />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSearchOpen(true)
            }}
            onFocus={() => setSearchOpen(true)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setSearchOpen(false)
              if (e.key === 'Enter' && hits[0]) onSelectHit(hits[0])
            }}
            placeholder="Search in paper"
            aria-label="Search in paper"
            className="h-8 w-44 rounded-md border border-border bg-surface pr-7 pl-8 text-small text-text placeholder:text-subtle focus-visible:border-primary focus-visible:outline-none sm:w-60"
          />
          {query && (
            <button
              aria-label="Clear search"
              onClick={() => {
                setQuery('')
                setHighlight(null)
              }}
              className="absolute right-1.5 rounded p-0.5 text-subtle hover:text-text"
            >
              <X className="size-3.5" />
            </button>
          )}
          {searchOpen && <SearchPanel hits={hits} query={query} onSelect={onSelectHit} />}
        </div>
      </div>
      <div className="relative flex min-h-0 flex-1">
        {tocOpen && (
          <nav
            aria-label="Table of contents"
            className="absolute inset-y-0 left-0 z-20 w-64 shrink-0 overflow-y-auto border-r border-border bg-surface p-2 shadow-lg lg:static lg:shadow-none"
          >
            <p className="px-2 pt-1 pb-2 text-caption font-medium tracking-wide text-subtle uppercase">
              Contents
            </p>
            <Toc nodes={toc} onSelect={onSelectSection} activePage={current} />
          </nav>
        )}
        <div ref={scrollRef} className="min-w-0 flex-1 overflow-auto bg-surface-muted/60" onClick={() => setSearchOpen(false)}>
          {paginated ? (
            <PdfPages
              structure={structure}
              pageTemplate={pageTemplate}
              scrollRef={scrollRef}
              highlight={highlight?.boxes ?? []}
              marks={markBoxes}
              onPageClick={passageActions ? onPageClick : undefined}
              zoom={zoom}
              onCurrentPage={onCurrentPage}
              registerNavigate={registerPdfNavigate}
            />
          ) : (
            <TextBody
              structure={structure}
              query={query}
              highlightStart={highlight?.charStart}
              markedStarts={markedStarts}
              onParagraphClick={passageActions ? selectParagraph : undefined}
              registerNavigate={registerTextNavigate}
            />
          )}
        </div>
        {selected && passageActions && (
          <div
            role="region"
            aria-label="Selected passage"
            className="absolute bottom-3 left-1/2 z-30 flex w-[min(40rem,calc(100%-1.5rem))] -translate-x-1/2 items-center gap-2 rounded-lg border border-border bg-surface-elevated px-3 py-2 shadow-lg animate-fade-in"
          >
            <p className="min-w-0 flex-1 text-caption text-muted">
              <span className="font-medium text-text">p. {selected.paragraph.page_start}</span>
              {selected.sectionTitle && ` · ${selected.sectionTitle}`}
              <span className="block truncate italic">“{selected.paragraph.text}”</span>
            </p>
            {passageActions(selected)}
            <IconButton label="Clear selection" onClick={() => setSelected(null)}>
              <X className="size-4" />
            </IconButton>
          </div>
        )}
      </div>
    </div>
  )
}

// --- PDF pages ---------------------------------------------------------------------------------

function PdfPages({
  structure,
  pageTemplate,
  scrollRef,
  highlight,
  marks,
  onPageClick,
  zoom,
  onCurrentPage,
  registerNavigate,
}: {
  structure: DocumentStructure
  pageTemplate: string
  scrollRef: React.RefObject<HTMLDivElement | null>
  highlight: Box[]
  marks: Box[]
  onPageClick?: (page: number, x: number, y: number) => void
  zoom: number
  onCurrentPage: (page: number) => void
  registerNavigate: (fn: (page: number, boxes?: Box[]) => void) => void
}) {
  const [containerWidth, setContainerWidth] = useState(800)
  const pageRefs = useRef(new Map<number, HTMLDivElement>())
  const total = structure.pages.length
  const baseWidth = Math.min(containerWidth - 32, 900)
  const width = Math.round(baseWidth * zoom)
  const imageWidth = renderWidth(width, window.devicePixelRatio)

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [scrollRef])

  useEffect(() => {
    const root = scrollRef.current
    if (!root) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible) {
          onCurrentPage(Number((visible.target as HTMLElement).dataset.page))
        }
      },
      { root, threshold: [0.25, 0.5, 0.75] },
    )
    pageRefs.current.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [scrollRef, total, width, onCurrentPage])

  const goTo = useCallback(
    function goTo(page: number, boxes?: Box[], attempt = 0) {
      const clamped = Math.min(Math.max(page, 1), total)
      const element = pageRefs.current.get(clamped)
      const root = scrollRef.current
      if (!element || !root) return
      // Navigating from another tab: the reader is still hidden (display: none) until the
      // tab switch renders, and scrolling a hidden element is a no-op. Retry for a few frames.
      if (root.clientHeight === 0) {
        if (attempt < 30) requestAnimationFrame(() => goTo(page, boxes, attempt + 1))
        return
      }
      const info = structure.pages[clamped - 1]
      const box = boxes?.find((b) => b[0] === clamped)
      const offset =
        box && info?.height ? (box[2] / info.height) * element.offsetHeight - 80 : -12
      root.scrollTo({ top: element.offsetTop + Math.max(offset, -12), behavior: 'smooth' })
    },
    [scrollRef, structure.pages, total],
  )

  useEffect(() => registerNavigate(goTo), [goTo, registerNavigate])

  return (
    <div className="flex flex-col items-center gap-4 py-4">
        {structure.pages.map((page) => {
          const ratio = page.width && page.height ? page.height / page.width : 1.294
          const boxes = highlight.filter((b) => b[0] === page.number)
          const pageMarks = marks.filter((b) => b[0] === page.number)
          return (
            <div
              key={page.number}
              data-page={page.number}
              ref={(el) => {
                if (el) pageRefs.current.set(page.number, el)
                else pageRefs.current.delete(page.number)
              }}
              className={cn('relative shrink-0 bg-white shadow-md', onPageClick && 'cursor-pointer')}
              style={{ width, height: Math.round(width * ratio) }}
              aria-label={`Page ${page.number}`}
              title={onPageClick ? 'Click a paragraph to note or bookmark it' : undefined}
              onClick={(event) => {
                if (!onPageClick || !page.width || !page.height) return
                const rect = event.currentTarget.getBoundingClientRect()
                onPageClick(
                  page.number,
                  ((event.clientX - rect.left) / rect.width) * page.width,
                  ((event.clientY - rect.top) / rect.height) * page.height,
                )
              }}
            >
              <img
                src={pageTemplate
                  .replace('{page}', String(page.number))
                  .replace('{width}', String(imageWidth))}
                alt={`Page ${page.number}`}
                loading="lazy"
                decoding="async"
                className="h-full w-full select-none"
                draggable={false}
              />
              {page.width &&
                page.height &&
                boxes.map((box, i) => (
                  <div
                    key={i}
                    className="pointer-events-none absolute rounded-sm bg-warning/25 ring-2 ring-warning/60 animate-fade-in"
                    style={{
                      left: `${(box[1] / page.width!) * 100}%`,
                      top: `${(box[2] / page.height!) * 100}%`,
                      width: `${((box[3] - box[1]) / page.width!) * 100}%`,
                      height: `${((box[4] - box[2]) / page.height!) * 100}%`,
                    }}
                  />
                ))}
              {page.width &&
                page.height &&
                pageMarks.map((box, i) => (
                  <div
                    key={`mark-${i}`}
                    data-testid="annotation-mark"
                    className="pointer-events-none absolute border-l-2 border-primary/70 bg-primary/5"
                    style={{
                      left: `${(box[1] / page.width!) * 100 - 0.8}%`,
                      top: `${(box[2] / page.height!) * 100}%`,
                      width: `${((box[3] - box[1]) / page.width!) * 100 + 0.8}%`,
                      height: `${((box[4] - box[2]) / page.height!) * 100}%`,
                    }}
                  />
                ))}
              {page.used_ocr && (
                <span className="absolute top-2 right-2 rounded-sm bg-black/60 px-1.5 py-0.5 text-caption text-white">
                  OCR
                </span>
              )}
            </div>
          )
        })}
    </div>
  )
}

// --- Text (non-paginated) ----------------------------------------------------------------------

function TextBody({
  structure,
  query,
  highlightStart,
  markedStarts,
  onParagraphClick,
  registerNavigate,
}: {
  structure: DocumentStructure
  query: string
  highlightStart?: number
  markedStarts: Set<number>
  onParagraphClick?: (paragraph: Paragraph) => void
  registerNavigate: (fn: (charStart: number | null, sectionId?: string) => void) => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    registerNavigate((charStart, sectionId) => {
      const root = ref.current
      if (!root) return
      const selector =
        charStart !== null ? `[data-char-start="${charStart}"]` : `[data-section="${sectionId}"]`
      root.querySelector(selector)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [registerNavigate])

  return (
    <article ref={ref} className="mx-auto max-w-3xl px-6 py-8 text-[1.0625rem] leading-7 text-text">
      {structure.sections.map((section) => {
        const Heading = section.level <= 1 ? 'h2' : 'h3'
        return (
          <section key={section.id} data-section={section.id} className="mb-6">
            {section.kind !== 'preamble' && (
              <Heading className={cn('mb-3 text-text', section.level <= 1 ? 'text-h2' : 'text-h3')}>
                {section.number && <span className="mr-2 text-subtle">{section.number}</span>}
                {section.title}
              </Heading>
            )}
            {section.paragraphs.map((paragraph) => (
              <ParagraphView
                key={paragraph.char_start}
                paragraph={paragraph}
                query={query}
                active={highlightStart === paragraph.char_start}
                marked={markedStarts.has(paragraph.char_start)}
                onClick={onParagraphClick && (() => onParagraphClick(paragraph))}
              />
            ))}
          </section>
        )
      })}
    </article>
  )
}

function ParagraphView({
  paragraph,
  query,
  active,
  marked,
  onClick,
}: {
  paragraph: Paragraph
  query: string
  active: boolean
  marked?: boolean
  onClick?: () => void
}) {
  const common = {
    'data-char-start': paragraph.char_start,
    onClick,
    className: cn(
      'mb-4 rounded-sm transition-colors',
      marked && 'border-l-2 border-primary/60 pl-2',
      onClick && 'cursor-pointer hover:bg-surface-muted/60',
      active && 'bg-warning-soft ring-4 ring-warning-soft',
    ),
  }
  if (paragraph.kind === 'table') {
    const rows = parseMarkdownTable(paragraph.text)
    if (rows) {
      return (
        <div {...common}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-small">
              <thead>
                <tr>
                  {rows[0].map((cell, i) => (
                    <th key={i} className="border-b-2 border-border px-3 py-1.5 text-left font-semibold">
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(1).map((row, r) => (
                  <tr key={r} className="border-b border-border">
                    {row.map((cell, c) => (
                      <td key={c} className="px-3 py-1.5 tabular-nums">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )
    }
  }
  if (paragraph.kind === 'code' || paragraph.kind === 'equation') {
    return (
      <pre
        {...common}
        className={cn(common.className, 'overflow-x-auto rounded-md bg-surface-muted px-4 py-3 font-mono text-small')}
      >
        {paragraph.text}
      </pre>
    )
  }
  if (paragraph.kind === 'caption') {
    return (
      <p {...common} className={cn(common.className, 'text-small text-muted italic')}>
        <Highlighted text={paragraph.text} query={query} />
      </p>
    )
  }
  return (
    <p {...common}>
      {paragraph.kind === 'list_item' && <span className="mr-2 text-subtle">•</span>}
      <Highlighted text={paragraph.text} query={query} />
    </p>
  )
}
