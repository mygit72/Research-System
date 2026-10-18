import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { useCollections } from '@/hooks/useOrganization'
import { useProjects } from '@/hooks/useProjects'
import { useCreateWatch, useUpdateWatch } from '@/hooks/useWatches'
import type { Watch } from '@/types/api'

/** Create a watch (a saved arXiv topic to monitor) or edit one. */
export function WatchDialog({
  open,
  onOpenChange,
  watch,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  watch?: Watch
}) {
  const [name, setName] = useState(watch?.name ?? '')
  const [query, setQuery] = useState(watch?.query ?? '')
  const [collectionId, setCollectionId] = useState(watch?.collection_id ?? '')
  const [projectId, setProjectId] = useState(watch?.project_id ?? '')
  const [intervalHours, setIntervalHours] = useState(watch?.interval_hours ?? 24)
  const [threshold, setThreshold] = useState(watch?.relevance_threshold ?? 0.35)
  const [autoImport, setAutoImport] = useState(watch?.auto_import ?? false)
  const [synthesize, setSynthesize] = useState(watch?.synthesize ?? false)
  const [isPublic, setIsPublic] = useState(watch?.is_public ?? false)
  const collections = useCollections()
  const projects = useProjects()
  const create = useCreateWatch()
  const update = useUpdateWatch(watch?.id ?? '')
  const saving = create.isPending || update.isPending

  const submit = () => {
    const body = {
      name: name.trim(),
      query: query.trim(),
      collection_id: collectionId || null,
      project_id: projectId || null,
      interval_hours: intervalHours,
      relevance_threshold: threshold,
      auto_import: autoImport,
      synthesize,
      is_public: isPublic,
    }
    const onSuccess = () => onOpenChange(false)
    if (watch) update.mutate(body, { onSuccess })
    else create.mutate(body, { onSuccess })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={watch ? 'Edit watch' : 'New watch'}
      description={
        watch
          ? undefined
          : 'Save a topic, and the system will search arXiv for new matching papers on a schedule.'
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim() && query.trim()) submit()
        }}
      >
        <label className="block">
          <span className="mb-1 block text-small font-medium text-text">Name</span>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            autoFocus
            required
            placeholder="e.g. Efficient fine-tuning"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-small font-medium text-text">Topic / search terms</span>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={500}
            required
            placeholder="e.g. low rank adapters for large language models"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-small font-medium text-text">Add matches to</span>
            <select
              value={collectionId}
              onChange={(e) => setCollectionId(e.target.value)}
              className="h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text"
            >
              <option value="">No collection</option>
              {collections.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-small font-medium text-text">
              Linked project <span className="font-normal text-muted">(optional)</span>
            </span>
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text"
            >
              <option value="">None</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-small font-medium text-text">Check every</span>
            <select
              value={intervalHours}
              onChange={(e) => setIntervalHours(Number(e.target.value))}
              className="h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text"
            >
              <option value={6}>6 hours</option>
              <option value={24}>1 day</option>
              <option value={24 * 7}>1 week</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-small font-medium text-text">
              Relevance threshold <span className="font-normal text-muted">({threshold.toFixed(2)})</span>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="h-9 w-full"
            />
          </label>
        </div>
        <label className="flex items-start gap-2.5 rounded-md border border-border bg-surface-muted p-3">
          <input
            type="checkbox"
            checked={autoImport}
            onChange={(e) => setAutoImport(e.target.checked)}
            className="mt-0.5 size-4"
          />
          <span className="text-small text-text">
            Automatically add matching papers to my library
            <span className="mt-0.5 block text-caption text-muted">
              Off by default: new papers show up in a review queue instead, so you decide what gets added.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2.5 rounded-md border border-border bg-surface-muted p-3">
          <input
            type="checkbox"
            checked={synthesize}
            onChange={(e) => setSynthesize(e.target.checked)}
            className="mt-0.5 size-4"
          />
          <span className="text-small text-text">
            Write a literature review when 3+ new papers match
            <span className="mt-0.5 block text-caption text-muted">
              Imports the matching papers so they can be read, even if automatic add is off above.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2.5 rounded-md border border-border bg-surface-muted p-3">
          <input
            type="checkbox"
            checked={isPublic}
            onChange={(e) => setIsPublic(e.target.checked)}
            className="mt-0.5 size-4"
          />
          <span className="text-small text-text">
            Make this watch's activity public
            <span className="mt-0.5 block text-caption text-muted">
              Anyone with the link can see this watch's name, topic and matched papers (all
              already public on arXiv). No login required.
            </span>
          </span>
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" loading={saving} disabled={!name.trim() || !query.trim()}>
            {watch ? 'Save' : 'Create'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
