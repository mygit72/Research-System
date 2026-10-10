import { useState } from 'react'
import { FolderOpen, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { CollectionDialog } from '@/components/organization/Collections'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { useCollections } from '@/hooks/useOrganization'
import { timeAgo } from '@/lib/format'
import { COLLECTION_KINDS } from '@/lib/organization'

export function CollectionsPage() {
  const collections = useCollections()
  const [creating, setCreating] = useState(false)
  return (
    <PageContainer>
      <PageHeader
        title="Collections"
        description="Group papers, notes and chats for a project, a literature review, a thesis or a course."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden /> New collection
          </Button>
        }
      />
      {collections.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      ) : collections.isError ? (
        <ErrorState error={collections.error} onRetry={() => collections.refetch()} />
      ) : collections.data.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          className="rounded-lg border border-dashed border-border"
          title="No collections yet"
          description="Create one for a project, then add papers from the library or from a paper’s page. You can chat with a collection, compare its papers and export it to BibTeX."
          actions={
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden /> New collection
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {collections.data.map((c) => (
            <li key={c.id}>
              <Link
                to={`/collections/${c.id}`}
                className="group flex h-full flex-col rounded-lg border border-border bg-surface p-4 shadow-sm transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-md"
              >
                <div className="flex items-start gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary-soft">
                    <FolderOpen className="size-4 text-primary" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <h2 className="line-clamp-2 text-small font-semibold text-text group-hover:text-primary">{c.name}</h2>
                    <Badge className="mt-1">{COLLECTION_KINDS[c.kind]}</Badge>
                  </div>
                </div>
                {c.description && <p className="mt-3 line-clamp-2 text-small text-muted">{c.description}</p>}
                <p className="mt-auto pt-3 text-caption text-subtle">
                  {c.paper_count} paper{c.paper_count === 1 ? '' : 's'} · {c.note_count} note{c.note_count === 1 ? '' : 's'} · updated{' '}
                  {timeAgo(c.updated_at)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {creating && <CollectionDialog open={creating} onOpenChange={setCreating} />}
    </PageContainer>
  )
}
