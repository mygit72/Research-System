import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '@/lib/queryClient'
import { notificationsApi } from '@/services/api'
import type { Notification } from '@/types/api'
import { NotificationBell } from './NotificationBell'

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={children} />
          <Route path="/watches/:id" element={<p>Opened watch</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  queryClient.clear()
})

const notification = (over: Partial<Notification> = {}): Notification => ({
  id: 'n1',
  kind: 'agent_watch_digest',
  title: 'Found 2 new papers for "Adapters"',
  body: 'Low Rank Adapters at Scale',
  link: '/watches/w1',
  read_at: null,
  created_at: new Date().toISOString(),
  ...over,
})

describe('NotificationBell', () => {
  it('shows no unread badge when there is nothing unread', async () => {
    vi.spyOn(notificationsApi, 'unreadCount').mockResolvedValue({ unread: 0 })
    vi.spyOn(notificationsApi, 'list').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
    render(wrap(<NotificationBell />))
    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('shows the unread count, and marks a notification read and navigates on click', async () => {
    vi.spyOn(notificationsApi, 'unreadCount').mockResolvedValue({ unread: 1 })
    vi.spyOn(notificationsApi, 'list').mockResolvedValue({
      items: [notification()],
      total: 1,
      limit: 20,
      offset: 0,
    })
    const markRead = vi.spyOn(notificationsApi, 'markRead').mockResolvedValue(
      notification({ read_at: new Date().toISOString() }),
    )
    render(wrap(<NotificationBell />))

    const trigger = await screen.findByRole('button', { name: 'Notifications, 1 unread' })
    await userEvent.click(trigger)
    const item = await screen.findByText('Found 2 new papers for "Adapters"')
    await userEvent.click(item)

    expect(markRead).toHaveBeenCalledWith('n1')
    expect(await screen.findByText('Opened watch')).toBeInTheDocument()
  })

  it('marks everything read with "Mark all read"', async () => {
    vi.spyOn(notificationsApi, 'unreadCount').mockResolvedValue({ unread: 2 })
    vi.spyOn(notificationsApi, 'list').mockResolvedValue({
      items: [notification(), notification({ id: 'n2' })],
      total: 2,
      limit: 20,
      offset: 0,
    })
    const markAllRead = vi.spyOn(notificationsApi, 'markAllRead').mockResolvedValue({ marked: 2 })
    render(wrap(<NotificationBell />))

    await userEvent.click(await screen.findByRole('button', { name: 'Notifications, 2 unread' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Mark all read' }))
    expect(markAllRead).toHaveBeenCalledTimes(1)
  })
})
