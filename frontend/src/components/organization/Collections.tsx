import { useState } from 'react'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useMutation } from '@tanstack/react-query'
import { Check, FolderPlus, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { refreshOrganization, useCollections } from '@/hooks/useOrganization'
import { collectionsApi } from '@/services/api'
import { COLLECTION_KINDS } from '@/lib/organization'
import type { Collection, CollectionKind } from '@/types/api'

/** Create a collection (optionally with papers) or edit one. */
export function CollectionDialog({
  open,
  onOpenChange,
  collection,
  documentIds,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  collection?: Collection
  documentIds?: string[]
  onSaved?: (collection: Collection) => void
}) {
  const [name, setName] = useState(collection?.name ?? '')
  const [kind, setKind] = useState<CollectionKind>(collection?.kind ?? 'project')
  const [description, setDescription] = useState(collection?.description ?? '')
  const save = useMutation({
    mutationFn: () =>
      collection
        ? collectionsApi.update(collection.id, { name, kind, description })
        : collectionsApi.create({ name, kind, description, document_ids: documentIds }),
    onSuccess: (saved) => {
      toast.success(collection ? 'Collection updated' : `Created “${saved.name}”`)
      refreshOrganization()
      onOpenChange(false)
      onSaved?.(saved)
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={collection ? 'Edit collection' : 'New collection'}
      description={collection ? undefined : 'Group papers, notes and chats for a project, review, thesis or course.'}
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) save.mutate()
        }}
      >
        <label className="block">
          <span className="mb-1 block text-small font-medium text-text">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoFocus required placeholder="e.g. Thesis chapter 2" />
        </label>
        <label className="block">
          <span className="mb-1 block text-small font-medium text-text">Type</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as CollectionKind)}
            className="h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text"
          >
            {Object.entries(COLLECTION_KINDS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-small font-medium text-text">
            Description <span className="font-normal text-muted">(optional)</span>
          </span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            maxLength={4000}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-small text-text focus-visible:border-primary focus-visible:outline-none"
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending} disabled={!name.trim()}>
            {collection ? 'Save' : 'Create'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

const itemClass =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

/** "Add to collection": toggle a paper in and out of collections, or start a new one. */
export function CollectionMenu({ documentId, memberOf }: { documentId: string; memberOf: string[] }) {
  const collections = useCollections()
  const [creating, setCreating] = useState(false)
  const toggle = useMutation({
    mutationFn: async (collection: Collection) => {
      if (memberOf.includes(collection.id)) await collectionsApi.removePaper(collection.id, documentId)
      else await collectionsApi.addPapers(collection.id, [documentId])
    },
    onSuccess: (_, collection) => {
      toast.success(memberOf.includes(collection.id) ? `Removed from “${collection.name}”` : `Added to “${collection.name}”`)
      refreshOrganization()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <Button variant="secondary" size="sm">
            <FolderPlus className="size-4" aria-hidden /> Collections{memberOf.length > 0 && ` (${memberOf.length})`}
          </Button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content
            align="end"
            sideOffset={6}
            className="z-50 max-h-80 w-64 overflow-y-auto rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
          >
            <Dropdown.Label className="px-2 py-1.5 text-caption text-subtle">Add to collection</Dropdown.Label>
            {(collections.data ?? []).map((collection) => (
              <Dropdown.CheckboxItem
                key={collection.id}
                className={itemClass}
                checked={memberOf.includes(collection.id)}
                onSelect={(e) => {
                  e.preventDefault()
                  toggle.mutate(collection)
                }}
              >
                <span className="flex size-4 items-center justify-center">
                  <Dropdown.ItemIndicator>
                    <Check className="size-4 text-primary" />
                  </Dropdown.ItemIndicator>
                </span>
                <span className="truncate">{collection.name}</span>
              </Dropdown.CheckboxItem>
            ))}
            {collections.data?.length ? <Dropdown.Separator className="my-1 h-px bg-border" /> : null}
            <Dropdown.Item className={itemClass} onSelect={() => setCreating(true)}>
              <Plus className="size-4 text-muted" /> New collection…
            </Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
      {creating && <CollectionDialog open={creating} onOpenChange={setCreating} documentIds={[documentId]} />}
    </>
  )
}
