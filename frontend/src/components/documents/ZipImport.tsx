import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Field } from '@/components/ui/Input'
import { documentsApi } from '@/services/api'
import type { ZipImportResponse } from '@/types/api'

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** Imports a folder of papers as one .zip, optionally into a new collection (a project library). */
export function ZipImportButton() {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [collection, setCollection] = useState('')
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<ZipImportResponse | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const reset = () => {
    setFile(null)
    setCollection('')
    setProgress(0)
    setResult(null)
    importZip.reset()
  }
  const importZip = useMutation({
    mutationFn: () => documentsApi.importZip(file as File, collection, setProgress),
    onSuccess: (response) => {
      setResult(response)
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
      void queryClient.invalidateQueries({ queryKey: ['collections'] })
    },
  })

  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <Archive className="size-4" aria-hidden /> Import zip
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) reset()
        }}
        title="Import a zip of papers"
        description="Every PDF, DOCX, HTML, Markdown or text file inside is added like an upload. Folders are fine; anything left out is listed with the reason."
        className="max-w-lg"
      >
        {result ? (
          <div className="space-y-3">
            <p className="text-body text-text" role="status">
              {plural(result.items.length, 'paper')} imported
              {result.items.length ? ' — they’ll be ready to search in a moment.' : '.'}
            </p>
            {result.collection_id && (
              <p className="text-small">
                <Link to={`/collections/${result.collection_id}`} className="text-primary underline underline-offset-2">
                  Open the new collection
                </Link>
              </p>
            )}
            {result.errors.length > 0 && (
              <div role="alert">
                <h3 className="text-small font-medium text-error">{plural(result.errors.length, 'file')} couldn’t be added</h3>
                <ul className="mt-1 space-y-1 text-small text-muted">
                  {result.errors.map((e) => (
                    <li key={e.filename}>
                      <span className="font-medium text-text">{e.filename}:</span> {e.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.skipped.length > 0 && (
              <details className="text-small">
                <summary className="cursor-pointer font-medium text-text">{plural(result.skipped.length, 'file')} skipped</summary>
                <ul className="mt-1 space-y-1 text-muted">
                  {result.skipped.map((s) => (
                    <li key={s.filename}>
                      <span className="font-medium text-text">{s.filename}:</span> {s.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <div className="flex justify-end">
              <Button onClick={() => setOpen(false)}>Done</Button>
            </div>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (file) importZip.mutate()
            }}
          >
            <div className="space-y-1.5">
              <label htmlFor="zip-file" className="block text-small font-medium text-text">
                Zip file
              </label>
              <input
                ref={input}
                id="zip-file"
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-small text-muted file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-small file:text-text"
              />
            </div>
            <Field
              label="Put the papers in a new collection"
              description="Optional. A collection is what a research project draws its papers from."
              value={collection}
              onChange={(e) => setCollection(e.target.value)}
              maxLength={120}
              placeholder="e.g. Thesis reading"
            />
            {importZip.isPending && (
              <p className="text-small text-muted" role="status">
                {progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : 'Unpacking and adding the papers…'}
              </p>
            )}
            {importZip.error && (
              <p role="alert" className="text-small text-error">
                {importZip.error.message}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={importZip.isPending} disabled={!file}>
                Import
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  )
}
