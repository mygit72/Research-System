import { useState } from 'react'
import { MessageSquareQuote, Sparkles, Upload } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { usePreferenceSync } from '@/hooks/usePreferenceSync'
import { useAuth } from '@/stores/auth'

const steps = [
  {
    icon: Upload,
    title: 'Upload your papers',
    body: 'PDF, Word, Markdown, HTML or plain text — one file or a whole folder.',
  },
  {
    icon: Sparkles,
    title: 'We read and index them',
    body: 'Sections, figures, tables and references are extracted so everything is searchable.',
  },
  {
    icon: MessageSquareQuote,
    title: 'Ask and explore',
    body: 'Get answers that cite the exact page they came from, compare papers and find gaps.',
  },
]

/** One-screen welcome shown on first sign-in. Skippable; never shown again once dismissed. */
export function Onboarding() {
  const user = useAuth((s) => s.user)
  const sync = usePreferenceSync()
  const [dismissed, setDismissed] = useState(false)
  const open = !!user && !user.preferences.onboarding_completed && !dismissed

  const finish = () => {
    setDismissed(true)
    sync({ onboarding_completed: true })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && finish()}
      title="Welcome to Research Intelligence"
      description="Your papers become a workspace you can search, question and connect."
      className="max-w-lg"
    >
      <ol className="space-y-4">
        {steps.map(({ icon: Icon, title, body }, index) => (
          <li key={title} className="flex gap-3.5">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary-soft text-primary">
              <Icon className="size-4" aria-hidden />
            </div>
            <div>
              <p className="text-small font-medium text-text">
                <span className="text-subtle">Step {index + 1} · </span>
                {title}
              </p>
              <p className="text-small text-muted">{body}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={finish}>
          Skip
        </Button>
        <Button onClick={finish}>Get started</Button>
      </div>
    </Dialog>
  )
}
