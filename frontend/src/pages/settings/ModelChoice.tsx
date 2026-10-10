import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ExternalLink, Gift, KeyRound, Laptop, Server, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Field } from '@/components/ui/Input'
import { cn } from '@/lib/cn'
import { modelApi } from '@/services/api'
import type { ConnectionTest, FreeTier, ModelChoiceView, ModelPreset } from '@/types/api'

type Mode = 'server' | 'key' | 'local'
type ModeOption = { value: Mode; label: string; icon: typeof Server; description: string }

/** The three ways to run the AI features, worded for this server. */
function modes(view: ModelChoiceView): ModeOption[] {
  const free = view.free_tier
  return [
    free
      ? {
          value: 'server',
          label: 'Free shared model',
          icon: Gift,
          description: `Nothing to set up. Slower, up to ${free.daily_limit} requests a day.`,
        }
      : { value: 'server', label: "This server's model", icon: Server, description: 'Nothing to set up.' },
    {
      value: 'key',
      label: 'My own API key',
      icon: KeyRound,
      description: 'OpenAI, Gemini, Groq, OpenRouter or Mistral — several have free tiers.',
    },
    view.options.allow_local_models
      ? {
          value: 'local',
          label: 'A model on my computer',
          icon: Laptop,
          description: 'Ollama or any OpenAI-compatible server (LM Studio, vLLM, llama.cpp).',
        }
      : {
          value: 'local',
          label: 'Run it on my computer',
          icon: Laptop,
          description: 'Download the app and use a local model or your own key. Nothing leaves your computer.',
        },
  ]
}

/** Settings → AI: which language model the user's AI work runs on. */
export function ModelChoice() {
  const view = useQuery({ queryKey: ['model-choice'], queryFn: modelApi.get })
  if (view.isPending) return <Skeleton className="h-40 w-full" />
  if (view.isError) return <ErrorState error={view.error} onRetry={() => view.refetch()} />
  // Re-mount the form when the saved choice changes, so its fields start from what was saved.
  return <ModelChoiceForm key={view.data.choice?.updated_at ?? 'server'} view={view.data} />
}

function modeOf(view: ModelChoiceView): Mode {
  const saved = view.options.presets.find((p) => p.id === view.choice?.preset)
  if (!saved) return 'server' // nothing chosen, or the free shared model
  return saved.local ? 'local' : 'key'
}

function ModelChoiceForm({ view }: { view: ModelChoiceView }) {
  const queryClient = useQueryClient()
  const { presets } = view.options
  const saved = view.choice
  const free = view.free_tier
  const [mode, setMode] = useState<Mode>(modeOf(view))
  const group = presets.filter((p) => (mode === 'local' ? p.local : !p.local))
  const [presetId, setPresetId] = useState(saved?.preset ?? 'groq')
  const preset: ModelPreset | undefined =
    group.find((p) => p.id === presetId) ?? group.find((p) => p.available) ?? group[0]
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(saved && preset?.id === saved.preset ? saved.base_url : '')
  const [model, setModel] = useState(saved && preset?.id === saved.preset ? saved.model : '')
  const [test, setTest] = useState<ConnectionTest | null>(null)
  const keySaved = Boolean(saved?.has_key && saved.preset === preset?.id)
  const url = baseUrl || preset?.base_url || ''

  const done = (data: ModelChoiceView, message: string) => {
    queryClient.setQueryData(['model-choice'], data)
    queryClient.invalidateQueries({ queryKey: ['ai-status'] })
    toast.success(message)
  }
  const save = useMutation({
    mutationFn: () =>
      modelApi.save({
        preset: preset!.id,
        model,
        base_url: preset!.local ? url : undefined,
        api_key: apiKey || undefined,
      }),
    onSuccess: (data) => done(data, `Your AI work now runs on ${model} (${preset!.label}).`),
    onError: (error) => toast.error(error.message),
  })
  const reset = useMutation({
    mutationFn: modelApi.reset,
    onSuccess: (data) =>
      done(
        data,
        data.free_tier
          ? 'The free model is off for you. Choose a model to use the AI features.'
          : "Back to this server's model. Your saved key was deleted.",
      ),
    onError: (error) => toast.error(error.message),
  })
  const chooseFree = useMutation({
    mutationFn: () => modelApi.save({ preset: 'free', model: '' }),
    onSuccess: (data) => done(data, 'Your AI work now runs on the free shared model.'),
    onError: (error) => toast.error(error.message),
  })
  const check = useMutation({
    mutationFn: () =>
      modelApi.test({
        preset: preset!.id,
        base_url: preset!.local ? url : undefined,
        api_key: apiKey || undefined,
      }),
    onSuccess: (result) => {
      setTest(result)
      if (result.ok && !model && result.models.length === 1) setModel(result.models[0])
    },
    onError: (error) => setTest({ ok: false, models: [], message: error.message }),
  })

  const choosePreset = (id: string) => {
    setPresetId(id)
    setTest(null)
    setApiKey('')
    setBaseUrl('')
    setModel(saved?.preset === id ? saved.model : '')
  }
  const disabled = (value: Mode) => value === 'key' && !view.options.allow_user_api_keys
  // A public server can't reach a model on someone's computer: that tab explains their own copy.
  const ownCopy = mode === 'local' && !view.options.allow_local_models

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-small font-medium text-text" id="model-mode-label">
          Language model for your work
        </p>
        <div role="radiogroup" aria-labelledby="model-mode-label" className="grid gap-2 sm:grid-cols-3">
          {modes(view).map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={mode === option.value}
              disabled={disabled(option.value)}
              onClick={() => {
                setMode(option.value)
                setTest(null)
              }}
              className={cn(
                'rounded-md border px-3 py-2.5 text-left transition-colors',
                'disabled:cursor-not-allowed disabled:opacity-50',
                // Selected: a primary outline on the normal surface (muted text on a tinted
                // background fails contrast in the dark theme).
                mode === option.value
                  ? 'border-primary bg-surface ring-1 ring-primary'
                  : 'border-border bg-surface hover:bg-surface-muted',
              )}
            >
              <span className="flex items-center gap-1.5 text-small font-medium text-text">
                <option.icon className="size-4" aria-hidden />
                {option.label}
              </span>
              <span className="mt-1 block text-caption text-muted">{option.description}</span>
            </button>
          ))}
        </div>
      </div>

      {mode === 'server' && free && (
        <FreeModel
          free={free}
          hasKey={Boolean(saved?.has_key)}
          choosing={chooseFree.isPending}
          stopping={reset.isPending}
          onChoose={() => chooseFree.mutate()}
          onStop={() => reset.mutate()}
        />
      )}

      {mode === 'server' && !free && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border px-4 py-3">
          <p className="text-small text-text">
            <span className="font-mono">{view.server_default.model || 'not configured'}</span>{' '}
            <span className="text-muted">({view.server_default.provider}), set up by whoever runs this server.</span>
          </p>
          {saved ? (
            <Button variant="secondary" size="sm" loading={reset.isPending} onClick={() => reset.mutate()}>
              Use this server's model
            </Button>
          ) : (
            <Badge tone="success">In use</Badge>
          )}
        </div>
      )}

      {ownCopy && <RunYourOwn downloadUrl={view.download_url} />}

      {mode !== 'server' && !ownCopy && preset && (
        <form
          className="space-y-4 rounded-md border border-border px-4 py-4"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <div>
            <label htmlFor="model-provider" className="mb-1 block text-small font-medium text-text">
              Provider
            </label>
            <select
              id="model-provider"
              aria-describedby="model-provider-note"
              value={preset.id}
              onChange={(e) => choosePreset(e.target.value)}
              className="h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text"
            >
              {group.map((p) => (
                <option key={p.id} value={p.id} disabled={!p.available}>
                  {p.label}
                </option>
              ))}
            </select>
            <p id="model-provider-note" className="mt-1 text-caption text-muted">
              {preset.note}{' '}
              {preset.keys_url && (
                <a href={preset.keys_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
                  Get a key <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </p>
          </div>

          {preset.local && (
            <Field
              label="Address"
              value={url}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={preset.base_url || 'http://localhost:1234/v1'}
              description={preset.id === 'ollama' ? 'Where Ollama listens; the default is usually right.' : 'The server’s OpenAI-compatible base URL, ending in /v1.'}
            />
          )}

          {(preset.needs_key || preset.id === 'custom') && (
            <Field
              label={preset.needs_key ? `${preset.label} API key` : 'API key (optional)'}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={keySaved ? `Saved key ${saved!.key_hint} — leave empty to keep it` : 'Paste your key'}
              description="Encrypted on the server and never shown again (only its last 4 characters). Used only for your own requests; the server decrypts it to make them. Removed when you switch back or delete your account."
            />
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="secondary" size="sm" loading={check.isPending} onClick={() => check.mutate()}>
              Test connection
            </Button>
            {test && (
              <p role="status" className={cn('flex items-center gap-1.5 text-small', test.ok ? 'text-success' : 'text-error')}>
                {test.ok ? <CheckCircle2 className="size-4" aria-hidden /> : <XCircle className="size-4" aria-hidden />}
                {test.message}
              </p>
            )}
          </div>

          <Field
            label="Model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            list="model-choices"
            placeholder={test?.models.length ? 'Choose from the list or type a name' : 'Test the connection to list models'}
            description={
              preset.id === 'openrouter'
                ? 'Model names ending in “:free” cost nothing.'
                : preset.id === 'ollama'
                  ? 'Any model you have pulled (ollama pull <name>).'
                  : undefined
            }
            required
          />
          <datalist id="model-choices">
            {(test?.models ?? []).map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>

          <div className="flex justify-end">
            <Button type="submit" loading={save.isPending} disabled={!model}>
              Use this model
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}

/** The site's shared free model: what it costs in speed, allowance and privacy, then the choice. */
function FreeModel(props: {
  free: FreeTier
  hasKey: boolean
  choosing: boolean
  stopping: boolean
  onChoose: () => void
  onStop: () => void
}) {
  const { free } = props
  const resets = new Date(free.resets_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <div className="space-y-3 rounded-md border border-border px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-small text-text">
          <span className="font-medium">{free.label}</span>{' '}
          {free.label !== free.model && <span className="font-mono text-muted">{free.model}</span>}
        </p>
        {free.chosen && <Badge tone="success">In use</Badge>}
      </div>
      <ul className="list-disc space-y-1.5 pl-5 text-small text-text">
        <li>
          <strong>Free, and slower.</strong> Everyone on this site shares it, so an answer may wait
          its turn before it starts.
        </li>
        <li>
          <strong>
            {free.remaining_today} of {free.daily_limit} requests left today
          </strong>{' '}
          (back to {free.daily_limit} at {resets}). An answer is one request; a summary or a review
          uses several.
        </li>
        <li>
          <strong>It runs at {free.host}, not on this site.</strong> Your questions and the passages
          of your papers needed to answer them are sent there, and a free service may keep what it
          receives. For confidential work, use your own key or run the app on your computer.
        </li>
      </ul>
      <div className="flex justify-end">
        {free.chosen ? (
          <Button variant="secondary" size="sm" loading={props.stopping} onClick={props.onStop}>
            Stop using it
          </Button>
        ) : (
          <Button loading={props.choosing} onClick={props.onChoose}>
            {props.hasKey ? 'Use the free model (deletes my saved key)' : 'Use the free model'}
          </Button>
        )}
      </div>
    </div>
  )
}

/** On a public site: how to get your own copy, which is where local models and full privacy are. */
export function RunYourOwn({ downloadUrl }: { downloadUrl: string }) {
  return (
    <div className="space-y-3 rounded-md border border-border px-4 py-4 text-small text-text">
      <p>
        Your own copy runs entirely on your computer: your papers, questions and answers never
        leave it, and you can use any local model, or your own API key, without limits.
      </p>
      <ol className="list-decimal space-y-1 pl-5">
        <li>Install Python 3.12+, Node.js 20+ and Ollama (ollama.com).</li>
        <li>
          {downloadUrl ? (
            <a href={downloadUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary underline underline-offset-2">
              Download the app <ExternalLink className="size-3" aria-hidden />
            </a>
          ) : (
            'Get the app’s code from whoever runs this site'
          )}{' '}
          and open a terminal in its folder.
        </li>
        <li>
          Windows: <code className="font-mono">{'powershell -ExecutionPolicy Bypass -File scripts\\run-local.ps1'}</code>
          <br />
          macOS / Linux: <code className="font-mono">./scripts/run-local.sh</code>
        </li>
        <li>Open http://localhost:5173, create an account there, and pick your model in its Settings → AI.</li>
      </ol>
      <p className="text-caption text-muted">
        A site on the internet can’t reach a model on your computer, so local models are chosen in
        your own copy, not here.
      </p>
    </div>
  )
}
