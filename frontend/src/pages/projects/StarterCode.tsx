import { useQuery } from '@tanstack/react-query'
import { Check, Copy, Download, FileCode } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { cn } from '@/lib/cn'
import { reportFilename, saveBlob } from '@/lib/reports'
import { projectsApi } from '@/services/api'
import type { Project } from '@/types/api'

/** The generated starter project: every file with what it is for, a copy button and a zip. */
export function StarterCodeStep({ project }: { project: Project }) {
  const code = useQuery({
    queryKey: ['projects', 'code', project.id, project.updated_at],
    queryFn: () => projectsApi.code(project.id),
  })
  const [selected, setSelected] = useState('README.md')
  const [copied, setCopied] = useState(false)

  if (code.isPending) return <Skeleton className="h-64 w-full" />
  if (code.isError) return <ErrorState error={code.error} onRetry={() => code.refetch()} />
  const files = code.data.files
  const file = files.find((f) => f.path === selected) ?? files[0]

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(file.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('Copying isn’t available here — select the text instead.')
    }
  }
  const download = async () => {
    try {
      saveBlob(await projectsApi.export(project.id, 'code'), reportFilename(`${project.title} starter code`, 'zip'))
    } catch (error) {
      toast.error((error as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="mb-1">
          <h2 className="text-h2 text-text">Starter code</h2>
          <p className="mt-1 max-w-2xl text-small text-muted">
            A small Python project generated from your plan. The evaluation machinery is finished and tested; your approach and
            the baselines are marked TODO. It never reports a number for something that isn’t implemented.
          </p>
        </div>
        <Button onClick={download}>
          <Download className="size-4" aria-hidden /> Download .zip
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-[260px_minmax(0,1fr)]">
        <ul aria-label="Files" className="space-y-1">
          {files.map((f) => (
            <li key={f.path}>
              <button
                type="button"
                aria-current={f.path === file.path ? 'true' : undefined}
                onClick={() => setSelected(f.path)}
                className={cn(
                  'w-full rounded-md px-3 py-2 text-left transition-colors',
                  f.path === file.path ? 'bg-primary-soft' : 'hover:bg-surface-muted',
                )}
              >
                <span className="flex items-center gap-2 text-small font-medium text-text">
                  <FileCode className="size-3.5 text-subtle" aria-hidden /> {f.path}
                </span>
                <span className={cn('mt-0.5 block text-caption', f.path === file.path ? 'text-muted' : 'text-subtle')}>{f.purpose}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="min-w-0 rounded-lg border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-small font-medium text-text">{file.path}</span>
            <Button variant="ghost" size="sm" onClick={copy}>
              {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <pre
            tabIndex={0}
            aria-label={`Contents of ${file.path}`}
            className="max-h-[32rem] overflow-auto p-3 text-caption leading-relaxed text-text"
          >
            <code>{file.content}</code>
          </pre>
        </div>
      </div>
    </div>
  )
}
