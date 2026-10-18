import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { Bell } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadCount,
} from '@/hooks/useNotifications'
import type { Notification } from '@/types/api'

const itemClass =
  'flex cursor-default flex-col gap-0.5 rounded-sm px-2 py-1.5 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

export function NotificationBell() {
  const unread = useUnreadCount()
  const notifications = useNotifications()
  const navigate = useNavigate()
  const markRead = useMarkNotificationRead()
  const markAllRead = useMarkAllNotificationsRead()
  const count = unread.data?.unread ?? 0

  const open = (notification: Notification) => {
    if (notification.read_at === null) markRead.mutate(notification.id)
    if (notification.link) navigate(notification.link)
  }

  return (
    <Dropdown.Root>
      <Dropdown.Trigger
        aria-label={count > 0 ? `Notifications, ${count} unread` : 'Notifications'}
        className="relative flex size-8 items-center justify-center rounded-full text-muted hover:bg-surface-muted hover:text-text"
      >
        <Bell className="size-4.5" aria-hidden />
        {count > 0 && (
          <span className="absolute top-0.5 right-0.5 flex size-4 items-center justify-center rounded-full bg-error-soft text-[0.625rem] font-semibold text-error">
            {count > 9 ? '9+' : count}
          </span>
        )}
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="end"
          sideOffset={8}
          className="z-50 w-80 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
        >
          <div className="flex items-center justify-between px-2 py-1.5">
            <Dropdown.Label className="text-caption text-subtle">Notifications</Dropdown.Label>
            {count > 0 && (
              <button
                onClick={() => markAllRead.mutate()}
                className="text-caption font-medium text-primary hover:underline"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {notifications.data?.items.length ? (
              notifications.data.items.map((notification) => (
                <Dropdown.Item
                  key={notification.id}
                  className={cn(itemClass, notification.read_at === null && 'bg-primary-soft/40')}
                  onSelect={() => open(notification)}
                >
                  <span className="font-medium">{notification.title}</span>
                  <span className="text-caption text-muted">{notification.body}</span>
                  <span className="text-caption text-subtle">{timeAgo(notification.created_at)}</span>
                </Dropdown.Item>
              ))
            ) : (
              <p className="px-2 py-4 text-center text-small text-muted">
                Nothing yet — your watches will notify you here.
              </p>
            )}
          </div>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  )
}
