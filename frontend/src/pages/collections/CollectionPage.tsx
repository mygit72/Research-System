import { useState } from 'react'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, GitCompareArrows, MessagesSquare, MoreHorizontal, Pencil, Plus, Trash2, X } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { PaperPicker } from '@/components/documents/PaperPicker'
import { DocTypeLabel } from '@/components/documents/PaperViews'
import { StatusBadge } from '@/components/documents/StatusBadge'
import { CollectionDialog } from '@/components/organization/Collections'
import { NotesList } from '@/components/organization/Notes'
import { TagChip } from '@/components/organization/Tags'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/Card'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'
import { Tooltip } from '@/components/ui/Tooltip'
import { refreshOrganization } from '@/hooks/useOrganization'
import { MAX_COMPARE, MIN_COMPARE, compareLink, compareReason, download } from '@/lib/compare'
import { COLLECTION_KINDS, READING_STATUS } from '@/lib/organization'
import { request } from '@/services/http'
import { chatApi, collectionsApi } from '@/services/api'

const itemClass =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

export function CollectionPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [adding, setAdding] = useState(false)
  const query = useQuery({ queryKey: ['collections', id], queryFn: () => collectionsApi.get(id) })
  const collection = query.data

  const add = useMutation({
    mutationFn: (documentId: string) => collectionsApi.addPapers(id, [documentId]),
    onSuccess: () => refreshOrganization(),
    onError: (e) => toast.error(e.message),
  })
  const removePaper = useMutation({
    mutationFn: (documentId: string) => collectionsApi.removePaper(id, documentId),
    onSuccess: () => {
      toast.success('Removed from the collection')
      refreshOrganization()
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => collectionsApi.remove(id),
    onSuccess: () => {
      toast.success('Collection deleted')
      refreshOrganization()
      navigate('/collections', { replace: true })
    },
    onError: (e) => toast.error(e.message),
  })
  const chat = useMutation({
    mutationFn: () => chatApi.create({ collection_id: id, title: `About ${collection?.name ?? 'this collection'}` }),
    onSuccess: (conversation) => navigate(`/chat/${conversation.id}`),
    onError: (e) => toast.error(e.message),
  })
  const exportAs = async (format: 'bibtex' | 'ris') => {
    try {
      const text = await request<string>(collectionsApi.exportUrl(id, format), { raw: true })
      const name = (collection?.name ?? 'collection').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'collection'
      download(`${name}.${format === 'bibtex' ? 'bib' : 'ris'}`, text, format === 'bibtex' ? 'application/x-bibtex' : 'application/x-research-info-systems')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (query.isPending)
    return (
      <PageContainer>
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="mt-6 h-64 w-full" />
      </PageContainer>
    )
  if (query.isError || !collection)
    return (
      <PageContainer>
        <ErrorState error={query.error} title="We couldn't open this collection" onRetry={() => query.refetch()} />
      </PageContainer>
    )

  const docs = collection.documents
  const comparable = docs.filter((d) => !compareReason(d))
  const canCompare = comparable.length >= MIN_COMPARE && comparable.length <= MAX_COMPARE
  const ready = docs.some((d) => d.status === 'ready' && d.index_status === 'indexed')

  return (
    <PageContainer width="wide">
      <Link to="/collections" className="inline-flex items-center gap-1 text-small text-muted hover:text-text">
        <ArrowLeft className="size-3.5" /> Collections
      </Link>
      <header className="mt-3 mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-h1 text-balance text-text">{collection.name}</h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-small text-muted">
            <Badge>{COLLECTION_KINDS[collection.kind]}</Badge>
            {collection.paper_count} paper{collection.paper_count === 1 ? '' : 's'} · {collection.note_count} note
            {collection.note_count === 1 ? '' : 's'}
          </p>
          {collection.description && <p className="mt-2 max-w-prose text-body text-muted whitespace-pre-line">{collection.description}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Tooltip content={ready ? 'Ask questions answered only from these papers' : 'Add an indexed paper first'}>
            <span>
              <Button size="sm" onClick={() => chat.mutate()} loading={chat.isPending} disabled={!ready}>
                {!chat.isPending && <MessagesSquare className="size-4" aria-hidden />} Chat
              </Button>
            </span>
          </Tooltip>
          <Tooltip
            content={
              canCompare
                ? 'Compare these papers side by side'
                : `Comparisons take ${MIN_COMPARE} to ${MAX_COMPARE} indexed papers (this collection has ${comparable.length})`
            }
          >
            <span>
              <Button variant="secondary" size="sm" disabled={!canCompare} onClick={() => navigate(compareLink(comparable.map((d) => d.id)))}>
                <GitCompareArrows className="size-4" aria-hidden /> Compare
              </Button>
            </span>
          </Tooltip>
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <Button variant="secondary" size="sm" disabled={!docs.length}>
                <Download className="size-4" aria-hidden /> Export
              </Button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content align="end" sideOffset={6} className="z-50 w-60 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in">
                <Dropdown.Item className={itemClass} onSelect={() => void exportAs('bibtex')}>
                  BibTeX (.bib) — LaTeX, Overleaf
                </Dropdown.Item>
                <Dropdown.Item className={itemClass} onSelect={() => void exportAs('ris')}>
                  RIS (.ris) — Zotero, Mendeley, EndNote
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <Button variant="secondary" size="icon-sm" aria-label="More actions">
                <MoreHorizontal className="size-4" />
              </Button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content align="end" sideOffset={6} className="z-50 w-48 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in">
                <Dropdown.Item className={itemClass} onSelect={() => setEditing(true)}>
                  <Pencil className="size-4 text-muted" /> Edit details
                </Dropdown.Item>
                <Dropdown.Separator className="my-1 h-px bg-border" />
                <Dropdown.Item className={`${itemClass} text-error`} onSelect={() => setConfirmDelete(true)}>
                  <Trash2 className="size-4" /> Delete collection
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
        </div>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card>
          <CardHeader className="flex items-center justify-between gap-3">
            <CardTitle>Papers</CardTitle>
            <Button variant="secondary" size="sm" onClick={() => setAdding(!adding)} aria-expanded={adding}>
              <Plus className="size-4" aria-hidden /> Add papers
            </Button>
          </CardHeader>
          {adding && (
            <div className="border-b border-border px-5 py-3">
              <PaperPicker
                picked={docs.map((d) => d.id)}
                statuses={['ready', 'processing', 'queued', 'failed']}
                placeholder="Find a paper in your library…"
                onAdd={(doc) => add.mutate(doc.id, { onSuccess: () => toast.success(`Added “${doc.title}”`) })}
              />
            </div>
          )}
          {docs.length === 0 ? (
            <CardBody>
              <EmptyState
                icon={Plus}
                className="py-8"
                title="No papers yet"
                description="Add papers with “Add papers”, from the library’s checkboxes, or from a paper’s Collections menu."
              />
            </CardBody>
          ) : (
            <ul className="divide-y divide-border">
              {docs.map((doc) => (
                <li key={doc.id} className="flex items-start gap-3 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <Link to={`/papers/${doc.id}`} className="line-clamp-2 text-small font-medium text-text hover:text-primary">
                      {doc.title}
                    </Link>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-muted">
                      <span className="line-clamp-1">{[doc.authors_display, doc.year].filter(Boolean).join(' · ')}</span>
                      <DocTypeLabel type={doc.doc_type} />
                      {doc.reading_status && <Badge>{READING_STATUS[doc.reading_status]}</Badge>}
                      {doc.status !== 'ready' && <StatusBadge doc={doc} />}
                    </p>
                    {doc.tags.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {doc.tags.map((t) => (
                          <TagChip key={t.id} tag={t} />
                        ))}
                      </div>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove “${doc.title}” from the collection`}
                    onClick={() => removePaper.mutate(doc.id)}
                  >
                    <X className="size-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <section aria-labelledby="collection-notes">
          <h2 id="collection-notes" className="mb-3 text-h3 text-text">
            Notes
          </h2>
          <NotesList collectionId={collection.id} />
        </section>
      </div>

      {editing && <CollectionDialog open={editing} onOpenChange={setEditing} collection={collection} />}
      <Dialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this collection?"
        description="Its notes are deleted too. The papers stay in your library."
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
    </PageContainer>
  )
}
