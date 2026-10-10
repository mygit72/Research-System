import { useQuery } from '@tanstack/react-query'
import { BookOpen, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Skeleton } from '@/components/ui/Feedback'
import { cn } from '@/lib/cn'
import { projectsApi } from '@/services/api'
import type { GuideStep } from '@/types/api'

/** Text with `code` segments rendered as code. */
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/`([^`]+)`/).map((part, i) =>
        i % 2 ? (
          <code key={i} className="rounded bg-surface-muted px-1 py-0.5 text-caption text-text">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  )
}

function List({ title, items, tone }: { title: string; items: string[]; tone?: 'warn' }) {
  return (
    <div>
      <h4 className="text-small font-medium text-text">{title}</h4>
      <ul className={cn('mt-1 list-disc space-y-1 pl-5 text-small', tone === 'warn' ? 'text-muted' : 'text-muted')}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

/**
 * "How this step works": why it matters, numbered actions with their reasons, what you should end
 * up with, how to check it, common mistakes — and what is true of this project right now.
 */
export function StepGuidePanel({ projectId, step, version }: { projectId: string; step: GuideStep; version: string }) {
  const [open, setOpen] = useState(true)
  const guide = useQuery({
    queryKey: ['projects', 'guide', projectId, step, version],
    queryFn: () => projectsApi.guide(projectId, step),
    staleTime: 60_000,
  })
  const g = guide.data
  const bodyId = `guide-${step}`
  return (
    <section aria-label="Step guide" className="mb-6 rounded-lg border border-border bg-surface">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        <BookOpen className="size-4 text-primary" aria-hidden />
        <span className="text-small font-medium text-text">
          How this step works{g ? ` · step ${g.number} of ${g.of}` : ''}
        </span>
        <ChevronDown className={cn('ml-auto size-4 text-muted transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div id={bodyId} className="space-y-4 border-t border-border px-4 py-4">
          {guide.isPending && <Skeleton className="h-24 w-full" />}
          {guide.isError && <p className="text-small text-muted">The guide couldn’t be loaded.</p>}
          {g && (
            <>
              <div>
                <h4 className="text-small font-medium text-text">Why this step</h4>
                <p className="mt-1 text-small text-muted">{g.why}</p>
              </div>
              <div>
                <h4 className="text-small font-medium text-text">What to do</h4>
                <ol className="mt-1 space-y-2">
                  {g.actions.map((action, i) => (
                    <li key={action.title} className="flex gap-3 text-small">
                      <span
                        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-border text-caption tabular-nums text-subtle"
                        aria-hidden
                      >
                        {i + 1}
                      </span>
                      <span>
                        <span className="font-medium text-text">{action.title}.</span>{' '}
                        <span className="text-muted">
                          <Inline text={action.detail} />
                        </span>
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
              <div>
                <h4 className="text-small font-medium text-text">What you should end up with</h4>
                <p className="mt-1 text-small text-muted">{g.expected}</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <List title="How to check it’s good" items={g.checks} />
                <List title="Common mistakes" items={g.pitfalls} tone="warn" />
              </div>
              <div className="rounded-md bg-surface-muted p-3">
                <h4 className="text-small font-medium text-text">Your project right now</h4>
                <ul className="mt-1 space-y-1 text-small text-muted">
                  {g.yours.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
