import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { queryClient } from '@/lib/queryClient'
import { webhooksApi } from '@/services/api'
import type { WebhookPlatform } from '@/types/api'

function refreshWebhooks() {
  void queryClient.invalidateQueries({ queryKey: ['webhooks'] })
}

export function useWebhooks() {
  return useQuery({ queryKey: ['webhooks', 'list'], queryFn: webhooksApi.list })
}

const onError = (error: Error) => toast.error(error.message)

export function useSaveWebhook() {
  return useMutation({
    mutationFn: ({ platform, url }: { platform: WebhookPlatform; url: string }) =>
      webhooksApi.save(platform, url),
    onSuccess: () => {
      toast.success('Webhook saved')
      refreshWebhooks()
    },
    onError,
  })
}

export function useRemoveWebhook() {
  return useMutation({
    mutationFn: (platform: WebhookPlatform) => webhooksApi.remove(platform),
    onSuccess: () => {
      toast.success('Webhook removed')
      refreshWebhooks()
    },
    onError,
  })
}

export function useTestWebhook() {
  return useMutation({
    mutationFn: (platform: WebhookPlatform) => webhooksApi.test(platform),
    onSuccess: (result) => {
      if (result.ok) toast.success('Test message sent')
      else toast.error("Couldn't post to that webhook — check the URL and try again.")
    },
    onError,
  })
}
