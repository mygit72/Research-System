import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Field } from '@/components/ui/Input'
import { queryClient } from '@/lib/queryClient'
import { documentsApi } from '@/services/api'
import { ApiError } from '@/services/http'
import { diffMetadata, initialMetadataForm, type MetadataForm } from '@/lib/metadata'
import type { DocumentDetail, MetadataUpdate } from '@/types/api'

export function MetadataDialog({
  doc,
  open,
  onOpenChange,
}: {
  doc: DocumentDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [before] = useState(() => initialMetadataForm(doc))
  const [form, setForm] = useState(before)
  const save = useMutation({
    mutationFn: (patch: MetadataUpdate) => documentsApi.updateMetadata(doc.id, patch),
    onSuccess: (updated) => {
      queryClient.setQueryData(['documents', 'detail', doc.id], updated)
      void queryClient.invalidateQueries({ queryKey: ['documents', 'list'] })
      toast.success('Details saved. Your corrections are kept if the paper is reprocessed.')
      onOpenChange(false)
    },
  })
  const fill = useMutation({
    mutationFn: () => documentsApi.fillFromDoi(doc.id, form.doi.trim()),
    onSuccess: (updated) => {
      queryClient.setQueryData(['documents', 'detail', doc.id], updated)
      void queryClient.invalidateQueries({ queryKey: ['documents', 'list'] })
      toast.success('Details filled in from Crossref. They are kept if the paper is reprocessed.')
      onOpenChange(false)
    },
  })
  const fieldErrors = save.error instanceof ApiError ? save.error.fieldErrors : {}
  const set = (key: keyof MetadataForm) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    const patch = diffMetadata(before, form, doc)
    if (Object.keys(patch).length === 0) {
      onOpenChange(false)
      return
    }
    save.mutate(patch)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Edit paper details"
      description="Fix anything we extracted incorrectly."
      className="max-w-2xl"
    >
      <form onSubmit={onSubmit} className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        <Field label="Title" value={form.title} onChange={set('title')} error={fieldErrors.title} />
        <div className="space-y-1.5">
          <label htmlFor="authors" className="block text-small font-medium">
            Authors <span className="font-normal text-muted">(one per line)</span>
          </label>
          <textarea
            id="authors"
            rows={3}
            value={form.authors}
            onChange={set('authors')}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-body focus-visible:border-primary focus-visible:outline-none"
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Year" inputMode="numeric" value={form.year} onChange={set('year')} error={fieldErrors.year} />
          <div className="sm:col-span-2">
            <Field label="Venue" value={form.venue} onChange={set('venue')} placeholder="e.g. NeurIPS 2024" />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="DOI" value={form.doi} onChange={set('doi')} error={fieldErrors.doi} placeholder="10.xxxx/…" />
          <Field label="arXiv ID" value={form.arxiv_id} onChange={set('arxiv_id')} placeholder="2403.01234" />
        </div>
 
        <div className="-mt-2 flex flex-wrap items-center gap-3">
          <Button type="button" variant="secondary" size="sm" disabled={!form.doi.trim()} loading={fill.isPending} onClick={() => fill.mutate()}>
            Fill from DOI
          </Button>
          <span className="text-caption text-muted">Looks the DOI up at Crossref and replaces the title, authors, abstract, year and venue.</span>
        </div>
        {fill.error && <p role="alert" className="text-small text-error">{fill.error.message}</p>}
        <Field label="Keywords" value={form.keywords} onChange={set('keywords')} description="Comma-separated" />
        <div className="space-y-1.5">
          <label htmlFor="abstract" className="block text-small font-medium">
            Abstract
          </label>
          <textarea
            id="abstract"
            rows={6}
            value={form.abstract}
            onChange={set('abstract')}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-body focus-visible:border-primary focus-visible:outline-none"
          />
        </div>
        {save.error && !Object.keys(fieldErrors).length && (
          <p className="text-small text-error">{save.error.message}</p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            Save changes
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
