import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { webhooksApi } from '@/services/api'
import { NotificationChannels } from './NotificationChannels'

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

afterEach(() => vi.restoreAllMocks())

describe('NotificationChannels', () => {
  it('saves a new webhook URL', async () => {
    vi.spyOn(webhooksApi, 'list').mockResolvedValue([])
    const save = vi
      .spyOn(webhooksApi, 'save')
      .mockResolvedValue({ platform: 'slack', url_hint: '…xxxxxx', updated_at: new Date().toISOString() })
    render(wrap(<NotificationChannels />))

    const [slackInput] = await screen.findAllByRole('textbox')
    await userEvent.type(slackInput, 'https://hooks.slack.com/services/T0/B0/xxxxxxxxxxxxxxxxxxxx')
    const [saveButton] = screen.getAllByRole('button', { name: 'Save' })
    await userEvent.click(saveButton)

    expect(save).toHaveBeenCalledWith(
      'slack',
      'https://hooks.slack.com/services/T0/B0/xxxxxxxxxxxxxxxxxxxx',
    )
  })

  it('shows only the hint for a saved webhook, with Test and Remove actions', async () => {
    vi.spyOn(webhooksApi, 'list').mockResolvedValue([
      { platform: 'slack', url_hint: '…xxxxxx', updated_at: new Date().toISOString() },
    ])
    const test = vi.spyOn(webhooksApi, 'test').mockResolvedValue({ ok: true })
    render(wrap(<NotificationChannels />))

    expect(await screen.findByText('Currently saved, ending in …xxxxxx.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Test' }))
    expect(test).toHaveBeenCalledWith('slack')
  })

  it('removes a saved webhook', async () => {
    vi.spyOn(webhooksApi, 'list').mockResolvedValue([
      { platform: 'discord', url_hint: '…yyyyyy', updated_at: new Date().toISOString() },
    ])
    const remove = vi.spyOn(webhooksApi, 'remove').mockResolvedValue(undefined)
    render(wrap(<NotificationChannels />))

    await userEvent.click(await screen.findByRole('button', { name: 'Remove' }))
    expect(remove).toHaveBeenCalledWith('discord')
  })
})
