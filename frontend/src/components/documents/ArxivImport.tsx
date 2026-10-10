import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { parseRefs } from '@/lib/arxivRefs'
import { documentsApi } from '@/services/api'
import { ApiError } from '@/services/http'
import type { UploadResponse } from '@/types/api'

const MAX_REFS = 10
const NEWLINE = String.fromCharCode(10)

/** Adds papers from arXiv by id or link: the PDF plus arXiv's own title, authors and abstract. */
export function ArxivImportButton({ variant = 'secondary' }: { variant?: 'primary' | 'secondary' }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [failed, setFailed] = useState<UploadResponse['errors']>([])
  const queryClient = useQueryClient()
  const refs = parseRefs(text)
  const tooMany = refs.length > MAX_REFS

  // One request per paper, so each failure keeps its own reason.
  const importPapers = useMutation({
    mutationFn: async (): Promise<UploadResponse> => {
      const result: UploadResponse = { items: [], errors: [] }
      for (const ref of refs) {
        try {
          result.items.push(...(await documentsApi.importPapers([ref])).items)
        } catch (error) {
          const e = error instanceof ApiError ? error : null
          result.errors.push({ filename: ref, message: e?.message ?? 'The import failed.', hint: e?.hint ?? null })
        }
      }
      return result
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
      setFailed(result.errors)
      if (result.items.length) toast.success(`${result.items.length} paper${result.items.length === 1 ? '' : 's'} imported.`)
      if (!result.errors.length) {
        setOpen(false)
        setText('')
      } else {
        setText(result.errors.map((e) => e.filename).join(NEWLINE)) // keep only what still needs fixing
      }
    },
  })

  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>
        <Download className="size-4" aria-hidden /> Import from arXiv
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Import from arXiv"
        description="Paste arXiv ids, links or arXiv DOIs, one per line. The PDF is downloaded with arXiv’s own title, authors and abstract. Other DOIs have no PDF to fetch: upload the PDF, then use “Fill from DOI” on the paper."
      >
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (refs.length && !tooMany) importPapers.mutate()
          }}
        >
          <label htmlFor="arxiv-refs" className="mb-1.5 block text-small font-medium text-text">
            arXiv ids, links or DOIs
          </label>
          <textarea
            id="arxiv-refs"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder={'2310.11511\nhttps://arxiv.org/abs/2112.09118'}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-body text-text placeholder:text-subtle focus-visible:border-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/20"
          />
          {tooMany && (
            <p role="alert" className="mt-1 text-small text-error">
              Import up to {MAX_REFS} papers at a time.
            </p>
          )}
          {failed.length > 0 && (
            <ul role="alert" className="mt-3 space-y-1 text-small text-error">
              {failed.map((f) => (
                <li key={f.filename + f.message}>
                  {f.filename && <span className="font-medium">{f.filename}: </span>}
                  {f.message}
                  {f.hint && <span className="text-muted"> {f.hint}</span>}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={importPapers.isPending} disabled={!refs.length || tooMany}>
              Import {refs.length > 1 ? `${refs.length} papers` : 'paper'}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  )
}
