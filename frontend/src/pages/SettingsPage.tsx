import { useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Laptop, Monitor, Moon, Sun } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardBody, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Field, Input } from '@/components/ui/Input'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { usePreferenceSync } from '@/hooks/usePreferenceSync'
import { cn } from '@/lib/cn'
import { saveBlob } from '@/lib/reports'
import { accountApi, authApi, systemApi } from '@/services/api'
import { ApiError } from '@/services/http'
import { useAuth } from '@/stores/auth'
import { usePreferences } from '@/stores/preferences'
import { ModelChoice } from './settings/ModelChoice'
import { NotificationChannels } from './settings/NotificationChannels'
import { PrivacyFacts } from './settings/PrivacyFacts'
import type { FontScale, Theme } from '@/types/api'

function Section({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardBody className="space-y-6">{children}</CardBody>
    </Card>
  )
}

function ProfileForm() {
  const user = useAuth((s) => s.user)!
  const setUser = useAuth((s) => s.setUser)
  const [name, setName] = useState(user.full_name)
  const save = useMutation({
    mutationFn: () => accountApi.update({ full_name: name }),
    onSuccess: (updated) => {
      setUser(updated)
      toast.success('Profile updated')
    },
    onError: (error) => toast.error(error.message),
  })
  return (
    <form
      className="grid gap-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} />
      <Field label="Email" value={user.email} disabled description="Email can't be changed yet." />
      <div className="sm:col-span-2">
        <Button type="submit" variant="secondary" loading={save.isPending} disabled={name === user.full_name}>
          Save profile
        </Button>
      </div>
    </form>
  )
}

function PasswordForm() {
  const setTokens = useAuth((s) => s.setTokens)
  const queryClient = useQueryClient()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const change = useMutation({
    mutationFn: () => authApi.changePassword({ current_password: current, new_password: next }),
    onSuccess: (tokens) => {
      setTokens(tokens)
      setCurrent('')
      setNext('')
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      toast.success('Password changed. Other devices have been signed out.')
    },
  })
  const fieldErrors = change.error instanceof ApiError ? change.error.fieldErrors : {}
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    change.mutate()
  }
  return (
    <form className="grid gap-4 sm:grid-cols-2" onSubmit={onSubmit}>
      <Field
        label="Current password"
        type="password"
        autoComplete="current-password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        error={
          change.error && !Object.keys(fieldErrors).length ? change.error.message : undefined
        }
      />
      <Field
        label="New password"
        type="password"
        autoComplete="new-password"
        value={next}
        onChange={(e) => setNext(e.target.value)}
        error={fieldErrors.new_password}
        description="At least 10 characters, mixing letters with numbers or symbols."
      />
      <div className="sm:col-span-2">
        <Button type="submit" variant="secondary" loading={change.isPending} disabled={!current || !next}>
          Change password
        </Button>
      </div>
    </form>
  )
}

function describeAgent(userAgent: string) {
  if (!userAgent) return 'Unknown device'
  const browser = /Edg\//.test(userAgent)
    ? 'Edge'
    : /Chrome\//.test(userAgent)
      ? 'Chrome'
      : /Firefox\//.test(userAgent)
        ? 'Firefox'
        : /Safari\//.test(userAgent)
          ? 'Safari'
          : 'Browser'
  const os = /Windows/.test(userAgent)
    ? 'Windows'
    : /Mac OS/.test(userAgent)
      ? 'macOS'
      : /Android/.test(userAgent)
        ? 'Android'
        : /iPhone|iPad/.test(userAgent)
          ? 'iOS'
          : /Linux/.test(userAgent)
            ? 'Linux'
            : ''
  return os ? `${browser} on ${os}` : browser
}

function Sessions() {
  const queryClient = useQueryClient()
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: accountApi.sessions })
  const revoke = useMutation({
    mutationFn: accountApi.revokeSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      toast.success('Session signed out')
    },
    onError: (error) => toast.error(error.message),
  })
  if (sessions.isPending) return <Skeleton className="h-16 w-full" />
  if (sessions.isError) return <ErrorState error={sessions.error} onRetry={() => sessions.refetch()} />
  return (
    <ul className="max-h-80 divide-y divide-border overflow-y-auto rounded-md border border-border">
      {sessions.data.map((session) => (
        <li key={session.id} className="flex items-center gap-3 px-4 py-3">
          <Laptop className="size-4 shrink-0 text-muted" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-small font-medium text-text">
              {describeAgent(session.user_agent)}
            </p>
            <p className="text-caption text-muted">
              Signed in {new Date(session.created_at).toLocaleString()}
              {session.ip_address && ` · ${session.ip_address}`}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => revoke.mutate(session.id)}
            loading={revoke.isPending && revoke.variables === session.id}
          >
            Sign out
          </Button>
        </li>
      ))}
    </ul>
  )
}

function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string; icon?: typeof Sun }[]
  onChange: (value: T) => void
}) {
  return (
    <div>
      <p className="mb-2 text-small font-medium text-text" id={`${label}-label`}>
        {label}
      </p>
      <div
        role="radiogroup"
        aria-labelledby={`${label}-label`}
        className="inline-flex rounded-md border border-border bg-surface-muted p-0.5"
      >
        {options.map((option) => (
          <button
            key={option.value}
            role="radio"
            aria-checked={value === option.value}
            onClick={() => onChange(option.value)}
            className={cn(
              'flex h-8 items-center gap-1.5 rounded-sm px-3 text-small transition-colors',
              value === option.value
                ? 'bg-surface font-medium text-text shadow-sm'
                : 'text-muted hover:text-text',
            )}
          >
            {option.icon && <option.icon className="size-3.5" aria-hidden />}
            {option.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function Appearance() {
  const { theme, fontScale, setTheme, setFontScale } = usePreferences()
  const sync = usePreferenceSync()
  return (
    <>
      <SegmentedControl<Theme>
        label="Theme"
        value={theme}
        onChange={(value) => {
          setTheme(value)
          sync({ theme: value })
        }}
        options={[
          { value: 'light', label: 'Light', icon: Sun },
          { value: 'dark', label: 'Dark', icon: Moon },
          { value: 'system', label: 'System', icon: Monitor },
        ]}
      />
      <SegmentedControl<FontScale>
        label="Text size"
        value={fontScale}
        onChange={(value) => {
          setFontScale(value)
          sync({ font_scale: value })
        }}
        options={[
          { value: 'sm', label: 'Compact' },
          { value: 'md', label: 'Default' },
          { value: 'lg', label: 'Large' },
        ]}
      />
    </>
  )
}

const STRATEGY_NAMES: Record<string, string> = {
  section_aware: 'Section-aware',
  semantic: 'Semantic',
  sentence: 'Sentence',
  recursive: 'Recursive',
  fixed: 'Fixed-size',
}

function AIConfiguration() {
  const config = useQuery({ queryKey: ['config'], queryFn: systemApi.config, staleTime: Infinity })
  const status = useQuery({ queryKey: ['ai-status'], queryFn: systemApi.aiStatus })
  if (config.isPending || status.isPending) return <Skeleton className="h-24 w-full" />
  if (config.isError) return <ErrorState error={config.error} onRetry={() => config.refetch()} />
  if (status.isError) return <ErrorState error={status.error} onRetry={() => status.refetch()} />
  const ai = status.data
  const languageModel =
    ai.llm.source === 'none'
      ? 'Not chosen yet'
      : ai.llm.source === 'free'
        ? `${ai.llm.model} · free shared model at ${ai.llm.host}${ai.llm.ready ? '' : ' (not ready)'}`
        : `${ai.llm.model} · ${ai.llm.label ?? ai.llm.provider}${ai.llm.remote ? ' API' : ', local'}${
            ai.llm.source === 'user' ? (ai.llm.key_hint ? ` (your key ${ai.llm.key_hint})` : ' (your choice)') : ''
          }${ai.llm.ready ? '' : ' (not ready)'}`
  const rows = [
    ['Language model', languageModel],
    [
      'Embedding model',
      `${ai.embedding.model} · ${ai.embedding.remote ? 'remote API' : `local, ${ai.embedding.device.toUpperCase()}`}`,
    ],
    [
      'Passages',
      `${STRATEGY_NAMES[ai.chunking.strategy] ?? ai.chunking.strategy}, up to ${ai.chunking.chunk_size} tokens`,
    ],
    ['Vector index', `Qdrant (${ai.vector_store.mode})`],
    [
      'Reranker',
      ai.reranker.model
        ? `${ai.reranker.model} · ${ai.reranker.remote ? 'remote API' : `local, ${ai.embedding.device.toUpperCase()}`}, top ${ai.reranker.candidates}`
        : 'Off',
    ],
    [
      'Answer checking',
      ai.verifier.model ? `${ai.verifier.model} (entailment)` : ai.verifier.provider === 'lexical' ? 'Word overlap' : 'Off',
    ],
  ]
  return (
    <>
      <dl className="divide-y divide-border rounded-md border border-border">
        {rows.map(([label, value]) => (
          <div key={label} className="flex flex-col gap-0.5 px-4 py-3 sm:flex-row sm:justify-between">
            <dt className="text-small text-muted">{label}</dt>
            <dd className="font-mono text-small text-text">{value}</dd>
          </div>
        ))}
      </dl>
      {!ai.llm.ready && (
        <p className="rounded-md border border-warning/30 bg-warning-soft px-4 py-3 text-small text-text">
          {ai.llm.problem} {ai.llm.hint && <span className="text-muted">{ai.llm.hint}</span>}
        </p>
      )}
      <p className="flex items-center gap-2 text-small text-muted">
        {config.data.local_only ? (
          <Badge tone="success">Local-only</Badge>
        ) : (
          <Badge tone="info">Remote providers allowed</Badge>
        )}
        Search models are configured by whoever runs this server.
      </p>
      <ModelChoice />
    </>
  )
}

function AdvancedToggle() {
  const showAdvanced = usePreferences((s) => s.showAdvanced)
  const setShowAdvanced = usePreferences((s) => s.setShowAdvanced)
  const sync = usePreferenceSync()
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4">
      <span>
        <span className="block text-small font-medium text-text">Show technical details</span>
        <span className="block text-small text-muted">
          Reveals the passages each paper was split into, search diagnostics and how each chat
          answer was found.
          Useful for understanding how search works; not needed for everyday use.
        </span>
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={showAdvanced}
        onChange={(e) => {
          setShowAdvanced(e.target.checked)
          sync({ show_advanced: e.target.checked })
        }}
        className="mt-1 size-4 accent-[var(--primary)]"
      />
    </label>
  )
}

const ACTIVITY: Record<string, string> = {
  'user.register': 'Account created',
  'user.login': 'Signed in',
  'user.login_failed': 'Failed sign-in attempt',
  'user.logout': 'Signed out',
  'user.password_changed': 'Password changed',
  'user.session_revoked': 'A session was signed out',
  'user.exported': 'Data exported',
  'document.deleted': 'Paper deleted',
  'auth.refresh_token_reuse': 'Reused sign-in token detected — all sessions were signed out',
}

function Activity() {
  const activity = useQuery({ queryKey: ['activity'], queryFn: accountApi.activity })
  if (activity.isPending) return <Skeleton className="h-16 w-full" />
  if (activity.isError) return <ErrorState error={activity.error} onRetry={() => activity.refetch()} />
  return (
    <ul className="max-h-72 divide-y divide-border overflow-y-auto rounded-md border border-border">
      {activity.data.map((event) => {
        const warning = event.action === 'user.login_failed' || event.action === 'auth.refresh_token_reuse'
        return (
          <li key={event.id} className="flex items-center gap-3 px-4 py-2.5">
            <p className={cn('min-w-0 flex-1 text-small', warning ? 'text-warning' : 'text-text')}>
              {ACTIVITY[event.action] ?? event.action}
            </p>
            <p className="shrink-0 text-caption text-muted">
              {new Date(event.created_at).toLocaleString()}
              {event.ip_address && ` · ${event.ip_address}`}
            </p>
          </li>
        )
      })}
    </ul>
  )
}

function ExportData() {
  const queryClient = useQueryClient()
  const exportData = useMutation({
    mutationFn: accountApi.exportData,
    onSuccess: (blob) => {
      saveBlob(blob, `research-intelligence-export-${new Date().toISOString().slice(0, 10)}.zip`)
      void queryClient.invalidateQueries({ queryKey: ['activity'] })
    },
    onError: (error) => toast.error(error.message),
  })
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-small font-medium text-text">Download your data</p>
        <p className="text-small text-muted">
          Everything you own as a .zip: your papers as uploaded, notes, conversations, summaries, reviews,
          projects and evaluation data, as JSON.
        </p>
      </div>
      <Button variant="secondary" onClick={() => exportData.mutate()} loading={exportData.isPending}>
        <Download className="size-4" aria-hidden /> Download
      </Button>
    </div>
  )
}

function DangerZone() {
  const [open, setOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const navigate = useNavigate()
  const remove = useMutation({
    mutationFn: accountApi.deleteAccount,
    onSuccess: () => {
      useAuth.setState({ status: 'anonymous', user: null, accessToken: null })
      navigate('/login', { replace: true })
      toast.success('Your account and data have been deleted.')
    },
    onError: (error) => toast.error(error.message),
  })
  return (
    <div className="flex flex-col gap-3 rounded-md border border-error/30 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-small font-medium text-text">Delete account</p>
        <p className="text-small text-muted">
          Permanently removes your account, papers, notes and conversations.
        </p>
      </div>
      <Button variant="danger" onClick={() => setOpen(true)}>
        Delete account
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Delete your account?"
        description="This cannot be undone. Type DELETE to confirm."
      >
        <Input
          aria-label="Type DELETE to confirm"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder="DELETE"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={confirmText !== 'DELETE'}
            loading={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Delete permanently
          </Button>
        </div>
      </Dialog>
    </div>
  )
}

export function SettingsPage() {
  return (
    <PageContainer width="narrow">
      <PageHeader title="Settings" description="Manage your account, appearance and privacy." />
      <div className="space-y-6">
        <Section title="Account" description="Your profile and sign-in details.">
          <ProfileForm />
          <div className="border-t border-border pt-6">
            <PasswordForm />
          </div>
        </Section>
        <Section title="Sessions" description="Devices currently signed in to your account.">
          <Sessions />
        </Section>
        <Section title="Security activity" description="Recent sign-ins and changes to your account.">
          <Activity />
        </Section>
        <Section title="Appearance" description="Saved to your account and applied on every device.">
          <Appearance />
        </Section>
        <Section title="AI" description="The models that power search and answers.">
          <AIConfiguration />
        </Section>
        <Section title="Notifications" description="Send a watch's found-papers alert to Slack or Discord too.">
          <NotificationChannels />
        </Section>
        <Section title="Advanced" description="Options for technical users.">
          <AdvancedToggle />
        </Section>
        <Section title="Privacy" description="Your data belongs to you.">
          <PrivacyFacts />
          <div className="border-t border-border pt-6">
            <ExportData />
          </div>
          <div className="border-t border-border pt-6">
            <DangerZone />
          </div>
        </Section>
      </div>
    </PageContainer>
  )
}
