import { useMutation, useQuery } from '@tanstack/react-query'
import { queryClient } from '@/lib/queryClient'
import { notificationsApi } from '@/services/api'

export function refreshNotifications() {
  void queryClient.invalidateQueries({ queryKey: ['notifications'] })
}

export function useUnreadCount() {
  return useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: notificationsApi.unreadCount,
    refetchInterval: 30_000,
  })
}

export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () => notificationsApi.list({ limit: 20 }),
    enabled,
  })
}

export function useMarkNotificationRead() {
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: refreshNotifications,
  })
}

export function useMarkAllNotificationsRead() {
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: refreshNotifications,
  })
}
