import { useQuery } from '@tanstack/react-query'
import { ExternalLink, ScanText, TriangleAlert } from 'lucide-react'
import type { OpenSource } from '@/components/chat/Sources'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/Card'
import { Tooltip } from '@/components/ui/Tooltip'
import { formatBytes, timeAgo } from '@/lib/format'
import { documentsApi } from '@/services/api'
import { SearchIndexCard } from './IndexTabs'
import { PaperEntitiesCard } from '@/components/knowledge/PaperKnowledge'
import { SummaryCard } from './SummaryCard'
import type { DocumentDetail, Provenance } from '@/types/api'

const SOURCE_LABELS: Record<string, string> = {
  layout: 'detected from the page layout',
  text: 'found in the text',
  arxiv_stamp: 'read from the arXiv stamp',
  arxiv_id: 'derived from the arXiv ID',
  embedded: 'read from the file’s embedded metadata',
  file_metadata: 'from the file’s creation date',
  heading: 'taken from the first heading',
  first_line: 'taken from the first line',
  filename: 'taken from the file name',
  section: 'from the Abstract section',
  user: 'edited by you',
}

function ProvenanceHint({ provenance }: { provenance?: Provenance }) {
  if (!provenance) return null
  const label = SOURCE_LABELS[provenance.source] ?? provenance.source
  const text =
    provenance.source === 'user'
      ? 'Edited by you'
      : `Automatically ${label} (${provenance.confidence} confidence)`
  return (
    <Tooltip content={text}>
      <span
        className={
          provenance.source === 'user'
            ? 'size-1.5 rounded-full bg-primary'
            : provenance.confidence === 'low'
              ? 'size-1.5 rounded-full bg-warning'
              : 'size-1.5 rounded-full bg-border-strong'
        }
        aria-label={text}
        role="img"
      />
    </Tooltip>
  )
}

function Row({
  label,
  field,
  doc,
  children,
}: {
  label: string
  field: string
  doc: DocumentDetail
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3 px-5 py-2.5">
      <dt className="flex items-center gap-2 text-small text-muted">
        {label}
        <ProvenanceHint provenance={doc.metadata?.provenance[field]} />
      </dt>
      <dd className="min-w-0 text-small break-words text-text">{children ?? <span className="text-subtle">Not found</span>}</dd>
    </div>
  )
}

export function OverviewTab({ doc, onOpenSource }: { doc: DocumentDetail; onOpenSource?: OpenSource }) {
  const meta = doc.metadata
  const version = doc.version
  const stats = version?.processing_config.stats ?? {}
  const versions = useQuery({
    queryKey: ['documents', 'versions', doc.id],
    queryFn: () => documentsApi.versions(doc.id),
    enabled: doc.version_count > 1,
  })

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Abstract</CardTitle>
          </CardHeader>
          <CardBody>
            {meta?.abstract ? (
              <p className="max-w-prose text-body leading-7 text-text">{meta.abstract}</p>
            ) : (
              <p className="text-small text-muted">
                No abstract was detected. You can add one with “Edit details”.
              </p>
            )}
            {meta?.keywords.length ? (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {meta.keywords.map((k) => (
                  <Badge key={k}>{k}</Badge>
                ))}
              </div>
            ) : null}
          </CardBody>
        </Card>

        <SummaryCard doc={doc} onOpenSource={onOpenSource} />
        <PaperEntitiesCard documentId={doc.id} ready={doc.status === 'ready'} />
      </div>

      <div className="space-y-6">
        {(version?.used_ocr || doc.warnings.length > 0) && (
          <Card className="border-warning/40 bg-warning-soft/40">
            <CardBody className="space-y-2">
              {version?.used_ocr && (
                <p className="flex gap-2 text-small text-text">
                  <ScanText className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                  <span>
                    Some pages were scanned images, so we used OCR to read them
                    {version.ocr_pages.length ? ` (pages ${version.ocr_pages.join(', ')})` : ''}.
                    Text on those pages may contain recognition errors.
                  </span>
                </p>
              )}
              {doc.warnings.map((warning) => (
                <p key={warning} className="flex gap-2 text-small text-text">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                  {warning}
                </p>
              ))}
            </CardBody>
          </Card>
        )}

        <SearchIndexCard doc={doc} />

        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <dl className="divide-y divide-border">
            <Row label="Authors" field="authors" doc={doc}>
              {meta?.authors.length ? meta.authors.map((a) => a.name).join(', ') : null}
            </Row>
            {meta?.affiliations.length ? (
              <Row label="Affiliations" field="affiliations" doc={doc}>
                {meta.affiliations.join('; ')}
              </Row>
            ) : null}
            <Row label="Year" field="year" doc={doc}>
              {meta?.publication_date ?? meta?.year ?? null}
            </Row>
            <Row label="Venue" field="venue" doc={doc}>
              {meta?.venue ?? null}
            </Row>
            <Row label="DOI" field="doi" doc={doc}>
              {meta?.doi ? (
                <a
                  href={`https://doi.org/${meta.doi}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  {meta.doi} <ExternalLink className="size-3" />
                </a>
              ) : null}
            </Row>
            <Row label="arXiv" field="arxiv_id" doc={doc}>
              {meta?.arxiv_id ? (
                <a
                  href={`https://arxiv.org/abs/${meta.arxiv_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  {meta.arxiv_id} <ExternalLink className="size-3" />
                </a>
              ) : null}
            </Row>
            <Row label="Research area" field="research_area" doc={doc}>
              {meta?.research_area ?? null}
            </Row>
          </dl>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>File</CardTitle>
          </CardHeader>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-5 py-4 text-small">
            <dt className="text-muted">Name</dt>
            <dd className="truncate text-text" title={doc.original_filename}>
              {doc.original_filename}
            </dd>
            {version && (
              <>
                <dt className="text-muted">Size</dt>
                <dd>{formatBytes(version.file_size)}</dd>
              </>
            )}
            {doc.page_count && (
              <>
                <dt className="text-muted">Pages</dt>
                <dd>{doc.page_count}</dd>
              </>
            )}
            {typeof stats.sections === 'number' && (
              <>
                <dt className="text-muted">Extracted</dt>
                <dd>
                  {stats.sections} sections, {String(stats.tables)} tables, {String(stats.figures)}{' '}
                  figures, {String(stats.references)} references
                </dd>
              </>
            )}
            <dt className="text-muted">Added</dt>
            <dd>{timeAgo(doc.created_at)}</dd>
          </dl>
          {doc.version_count > 1 && versions.data && (
            <div className="border-t border-border px-5 py-3">
              <p className="mb-2 text-caption font-medium text-subtle uppercase">Versions</p>
              <ul className="space-y-1.5 text-small">
                {versions.data.map((v) => (
                  <li key={v.id} className="flex justify-between gap-2">
                    <span className="truncate">
                      v{v.version_number} · {v.original_filename}
                    </span>
                    <span className="shrink-0 text-muted">
                      {v.id === version?.id ? 'current' : timeAgo(v.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
