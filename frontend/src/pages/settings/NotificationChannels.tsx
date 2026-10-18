import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Field } from '@/components/ui/Input'
import { useRemoveWebhook, useSaveWebhook, useTestWebhook, useWebhooks } from '@/hooks/useWebhooks'
import type { Webhook, WebhookPlatform } from '@/types/api'

const LABELS: Record<WebhookPlatform, string> = { slack: 'Slack', discord: 'Discord' }
const PLACEHOLDERS: Record<WebhookPlatform, string> = {
  slack: 'https://hooks.slack.com/services/…',
  discord: 'https://discord.com/api/webhooks/…',
}

function WebhookRow({ platform, saved }: { platform: WebhookPlatform; saved?: Webhook }) {
  const [url, setUrl] = useState('')
  const save = useSaveWebhook()
  const remove = useRemoveWebhook()
  const test = useTestWebhook()

  return (
    <div className="space-y-2">
      <Field
        label={`${LABELS[platform]} webhook URL`}
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder={saved ? `Saved (${saved.url_hint})` : PLACEHOLDERS[platform]}
        description={saved ? `Currently saved, ending in ${saved.url_hint}.` : undefined}
      />
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="secondary"
          loading={save.isPending}
          disabled={!url.trim()}
          onClick={() => save.mutate({ platform, url: url.trim() }, { onSuccess: () => setUrl('') })}
        >
          Save
        </Button>
        {saved && (
          <>
            <Button size="sm" variant="secondary" loading={test.isPending} onClick={() => test.mutate(platform)}>
              Test
            </Button>
            <Button size="sm" variant="ghost" loading={remove.isPending} onClick={() => remove.mutate(platform)}>
              Remove
            </Button>
          </>
        )}
      </div>
    </div>
  )
}

/** Settings -> Notifications: one Slack and/or Discord webhook, reused by every watch. */
export function NotificationChannels() {
  const webhooks = useWebhooks()
  if (webhooks.isPending) return <Skeleton className="h-24 w-full" />
  if (webhooks.isError) return <ErrorState error={webhooks.error} onRetry={() => webhooks.refetch()} />
  const byPlatform = Object.fromEntries(webhooks.data.map((w) => [w.platform, w])) as Partial<
    Record<WebhookPlatform, Webhook>
  >
  return (
    <div className="space-y-6">
      <WebhookRow platform="slack" saved={byPlatform.slack} />
      <WebhookRow platform="discord" saved={byPlatform.discord} />
    </div>
  )
}
