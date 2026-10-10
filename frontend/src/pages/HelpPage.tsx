import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/Card'
import { Kbd } from '@/components/ui/Feedback'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { modKeyLabel } from '@/hooks/useHotkeys'
import { systemApi } from '@/services/api'

const shortcuts: { keys: string[]; action: string }[] = [
  { keys: [modKeyLabel, 'K'], action: 'Open search & command palette' },
  { keys: ['/'], action: 'Go to search' },
  { keys: [modKeyLabel, 'U'], action: 'Upload papers' },
  { keys: ['Enter'], action: 'Send a question in chat' },
  { keys: ['Shift', 'Enter'], action: 'New line in a chat question' },
  { keys: ['Esc'], action: 'Close dialog or panel' },
  { keys: ['Tab'], action: 'Move between controls' },
]

export function HelpPage() {
  const config = useQuery({ queryKey: ['config'], queryFn: systemApi.config, staleTime: Infinity })
  const freeTier = config.data?.free_tier ?? false
  const downloadUrl = config.data?.download_url ?? ''
  return (
    <PageContainer width="narrow">
      <PageHeader title="Help" description="Get around quickly, with or without a mouse." />
      <Card>
        <CardHeader>
          <CardTitle>Keyboard shortcuts</CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          <dl className="divide-y divide-border">
            {shortcuts.map(({ keys, action }) => (
              <div key={action} className="flex items-center justify-between gap-4 px-5 py-3">
                <dt className="text-small text-text">{action}</dt>
                <dd className="flex shrink-0 gap-1">
                  {keys.map((key) => (
                    <Kbd key={key}>{key}</Kbd>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        </CardBody>
      </Card>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Choose the model that answers</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3 text-small text-text">
          <p>
            In <Link to="/settings" className="text-primary underline underline-offset-2">Settings → AI</Link> you
            choose what writes your answers. Chat, summaries, comparisons, reviews and the project
            builder all use your choice, and so does the starter code you download.
          </p>
          <ul className="list-disc space-y-1.5 pl-5">
            {freeTier ? (
              <li>
                <strong>The free shared model.</strong> Nothing to set up and nothing to pay. It is
                slower, because everyone on this site shares it, and it has a daily limit. It runs at
                another company, which receives your questions and the passages needed to answer
                them, so it is used only once you turn it on.
              </li>
            ) : (
              <li>
                <strong>This server’s model.</strong> Nothing to set up.
              </li>
            )}
            <li>
              <strong>Your own API key</strong> (OpenAI, Gemini, Groq, OpenRouter or Mistral;
              several have free tiers). No waiting and no daily limit from this site.
            </li>
            <li>
              <strong>Your own copy with a local model.</strong> Everything stays on your computer:
              see “Run it on your computer” below.
            </li>
          </ul>
          <p className="text-muted">
            Your key is encrypted on the server and never shown again (only its last four
            characters). It is used only for your requests — the server has to decrypt it to make
            them — and it is deleted when you switch back or delete your account.
          </p>
        </CardBody>
      </Card>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Who can see your work</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3 text-small text-text">
          <p>
            Nothing you add is public. There are no shared links, and no account — not even an
            administrator’s — can open another account’s papers, notes or chats. The app doesn’t
            write them to its logs either.
          </p>
          <p className="text-muted">
            Two limits to know about: a website stores your work on its server, which the people
            running it can technically reach, and a hosted model receives the questions you send
            it. If nobody else may ever see your work, run the app on your computer with a local
            model. <Link to="/settings" className="text-primary underline underline-offset-2">Settings → Privacy</Link>{' '}
            shows what applies to you now.
          </p>
        </CardBody>
      </Card>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Run it on your computer</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3 text-small text-text">
          <p>
            For full privacy, or to use any local model, run your own copy. Nothing leaves your
            computer, and every model you pull can be chosen in Settings → AI.
          </p>
          <ol className="list-decimal space-y-1 pl-5">
            <li>Install Python 3.12+, Node.js 20+ and Ollama (ollama.com).</li>
            <li>
              {downloadUrl ? (
                <a href={downloadUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary underline underline-offset-2">
                  Download this project’s code <ExternalLink className="size-3" aria-hidden />
                </a>
              ) : (
                'Download this project’s code'
              )}{' '}
              and open a terminal in its folder.
            </li>
            <li>
              Windows: <code className="font-mono">powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1</code>
              <br />
              macOS / Linux: <code className="font-mono">./scripts/run-local.sh</code>
            </li>
            <li>Open http://localhost:5173 and create an account (it stays on your computer).</li>
          </ol>
          <p className="text-muted">
            Add <code className="font-mono">-Model llama3.2:3b</code> (Windows) or a model name
            (macOS / Linux) to start with another model. The guide is docs/RUN_LOCALLY.md.
          </p>
        </CardBody>
      </Card>
    </PageContainer>
  )
}
