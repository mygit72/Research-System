import { BookMarked, Image as ImageIcon, Sigma, Table2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/Feedback'
import type { Box } from '@/lib/reader'
import { SaveActions } from '@/components/organization/SaveActions'
import type { Anchor, DocElement, DocReference, DocumentStructure } from '@/types/api'

type Navigate = (page: number, boxes?: Box[]) => void

function boxesFor(element: DocElement): Box[] | undefined {
  return element.bbox ? [[element.page, ...element.bbox]] : undefined
}

/** Crops a figure out of the rendered page image using its bounding box. */
function FigurePreview({
  element,
  structure,
  pageTemplate,
}: {
  element: DocElement
  structure: DocumentStructure
  pageTemplate: string | null
}) {
  const page = structure.pages.find((p) => p.number === element.page)
  if (!pageTemplate || !element.bbox || !page?.width || !page.height) return null
  const [x0, y0, x1, y1] = element.bbox
  const pad = 6
  const left = Math.max(0, x0 - pad)
  const top = Math.max(0, y0 - pad)
  const width = Math.min(page.width, x1 + pad) - left
  const height = Math.min(page.height, y1 + pad) - top
  const src = pageTemplate.replace('{page}', String(element.page)).replace('{width}', '1200')
  return (
    <div
      className="relative w-full overflow-hidden rounded-md border border-border bg-white"
      style={{ aspectRatio: `${width} / ${height}` }}
    >
      <img
        src={src}
        alt={element.caption ?? element.label ?? 'Figure'}
        loading="lazy"
        className="absolute max-w-none"
        style={{
          width: `${(page.width / width) * 100}%`,
          left: `${(-left / width) * 100}%`,
          top: `${(-top / height) * 100}%`,
        }}
      />
    </div>
  )
}

function elementTarget(element: DocElement): Anchor {
  return {
    page: element.page,
    element_id: element.id,
    boxes: boxesFor(element),
    quote: [element.label, element.caption].filter(Boolean).join(' — ').slice(0, 600) || undefined,
  }
}

export function FiguresTab({
  structure,
  pageTemplate,
  onNavigate,
  documentId,
}: {
  structure: DocumentStructure
  pageTemplate: string | null
  onNavigate: Navigate
  documentId?: string
}) {
  const figures = structure.elements.filter((e) => e.kind === 'figure')
  if (!figures.length)
    return (
      <EmptyState
        icon={ImageIcon}
        title="No figures detected"
        description="Figures are found through their captions (“Figure 1: …”). This paper doesn't seem to have any."
      />
    )
  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {figures.map((figure) => (
        <li key={figure.id}>
          <Card className="flex h-full flex-col p-4">
            <FigurePreview element={figure} structure={structure} pageTemplate={pageTemplate} />
            <p className="mt-3 text-small text-text">
              <span className="font-semibold">{figure.label}</span>
              {figure.caption && ` — ${figure.caption.replace(/^(figure|fig\.?)\s*\S+\s*[:.|—-]\s*/i, '')}`}
            </p>
            {figure.context && (
              <p className="mt-2 line-clamp-3 text-caption text-muted">{figure.context}</p>
            )}
            <div className="mt-auto flex items-center justify-between gap-2 pt-3">
              <Button variant="link" size="sm" onClick={() => onNavigate(figure.page, boxesFor(figure))}>
                View on page {figure.page}
              </Button>
              {documentId && (
                <SaveActions compact documentId={documentId} kind="figure" target={elementTarget(figure)} label={figure.label ?? ''} />
              )}
            </div>
          </Card>
        </li>
      ))}
    </ul>
  )
}

export function TablesTab({
  structure,
  onNavigate,
  documentId,
}: {
  structure: DocumentStructure
  onNavigate: Navigate
  documentId?: string
}) {
  const tables = structure.elements.filter((e) => e.kind === 'table')
  if (!tables.length)
    return (
      <EmptyState
        icon={Table2}
        title="No tables detected"
        description="We look for ruled tables and “Table N” captions. None were found in this paper."
      />
    )
  return (
    <div className="space-y-6">
      {tables.map((table) => {
        const rows = table.content.rows ?? []
        return (
          <Card key={table.id} className="overflow-hidden">
            <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-3">
              <p className="text-small text-text">
                <span className="font-semibold">{table.label ?? 'Table'}</span>
                {table.caption &&
                  ` — ${table.caption.replace(/^table\s*\S+\s*[:.|—-]\s*/i, '')}`}
              </p>
              <span className="flex shrink-0 items-center gap-1">
                {documentId && (
                  <SaveActions compact documentId={documentId} kind="table" target={elementTarget(table)} label={table.label ?? ''} />
                )}
                <Button variant="link" size="sm" onClick={() => onNavigate(table.page, boxesFor(table))}>
                  Page {table.page}
                </Button>
              </span>
            </div>
            {rows.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-small">
                  <thead className="bg-surface-muted/60">
                    <tr>
                      {rows[0].map((cell, i) => (
                        <th key={i} className="px-4 py-2 text-left font-semibold text-text">
                          {cell}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {rows.slice(1).map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, c) => (
                          <td key={c} className="px-4 py-2 text-text tabular-nums">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="px-5 py-4 text-small text-muted">
                The caption was found but the table's cells couldn't be extracted. Open the page to
                read it.
              </p>
            )}
          </Card>
        )
      })}
    </div>
  )
}

export function EquationsTab({
  structure,
  onNavigate,
}: {
  structure: DocumentStructure
  onNavigate: Navigate
}) {
  const equations = structure.elements.filter((e) => e.kind === 'equation')
  if (!equations.length)
    return (
      <EmptyState
        icon={Sigma}
        title="No equations detected"
        description="Display equations are detected from math fonts and symbols."
      />
    )
  return (
    <ul className="space-y-4">
      {equations.map((equation) => (
        <li key={equation.id}>
          <Card className="p-5">
            <div className="flex items-center justify-between gap-4">
              <p className="text-small font-semibold text-text">{equation.label ?? 'Unnumbered equation'}</p>
              <Button variant="link" size="sm" onClick={() => onNavigate(equation.page, boxesFor(equation))}>
                Page {equation.page}
              </Button>
            </div>
            <pre className="mt-3 overflow-x-auto rounded-md bg-surface-muted px-4 py-3 font-mono text-small text-text">
              {equation.content.text}
            </pre>
            {equation.context && (
              <p className="mt-3 text-caption text-muted">
                <span className="font-medium">Context: </span>
                {equation.context}
              </p>
            )}
            <p className="mt-2 text-caption text-subtle">
              Extracted text is shown exactly as found; complex notation may not render perfectly.
            </p>
          </Card>
        </li>
      ))}
    </ul>
  )
}

export function ReferencesTab({ references }: { references: DocReference[] }) {
  if (!references.length)
    return (
      <EmptyState
        icon={BookMarked}
        title="No reference list found"
        description="We look for a “References” or “Bibliography” section."
      />
    )
  return (
    <Card>
      <ol className="divide-y divide-border">
        {references.map((ref) => (
          <li key={ref.position} className="flex gap-4 px-5 py-3">
            <span className="w-6 shrink-0 text-right text-small text-subtle tabular-nums">
              {ref.position}
            </span>
            <div className="min-w-0 text-small">
              {ref.title && <p className="font-medium text-text">{ref.title}</p>}
              <p className="mt-0.5 text-muted">{ref.raw_text}</p>
              <div className="mt-1 flex gap-3 text-caption">
                {ref.doi && (
                  <a className="text-primary hover:underline" href={`https://doi.org/${ref.doi}`} target="_blank" rel="noreferrer">
                    DOI
                  </a>
                )}
                {ref.arxiv_id && (
                  <a className="text-primary hover:underline" href={`https://arxiv.org/abs/${ref.arxiv_id}`} target="_blank" rel="noreferrer">
                    arXiv
                  </a>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  )
}
