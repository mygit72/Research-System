import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import * as reports from '@/lib/reports'
import { accountApi, systemApi } from '@/services/api'
import { useAuth } from '@/stores/auth'
import { SettingsPage } from './SettingsPage'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Settings — privacy and security', () => {
  it('lists security activity and downloads a data export', async () => {
    useAuth.setState({ status: 'authenticated', user: { id: 'u1', email: 'a@b.c', full_name: 'A', preferences: {} } as never })
    vi.spyOn(accountApi, 'sessions').mockResolvedValue([])
    // The AI section isn't under test: leave its requests pending.
    vi.spyOn(systemApi, 'config').mockReturnValue(new Promise(() => {}))
    vi.spyOn(systemApi, 'aiStatus').mockReturnValue(new Promise(() => {}))
    vi.spyOn(accountApi, 'activity').mockResolvedValue([
      { id: '1', action: 'user.login_failed', resource_type: null, resource_id: null, ip_address: '10.0.0.9', created_at: '2026-10-02T10:00:00Z' },
      { id: '2', action: 'user.login', resource_type: null, resource_id: null, ip_address: '10.0.0.1', created_at: '2026-10-02T09:00:00Z' },
    ])
    const blob = new Blob(['zip'])
    const exportData = vi.spyOn(accountApi, 'exportData').mockResolvedValue(blob)
    const save = vi.spyOn(reports, 'saveBlob').mockImplementation(() => {})
    renderPage()

    expect(await screen.findByText('Failed sign-in attempt')).toBeInTheDocument()
    expect(screen.getByText('Signed in')).toBeInTheDocument()
    expect(screen.getByText(/10\.0\.0\.9/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Download/ }))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(exportData).toHaveBeenCalled()
    expect(save.mock.calls[0][0]).toBe(blob)
    expect(save.mock.calls[0][1]).toMatch(/^research-intelligence-export-\d{4}-\d{2}-\d{2}\.zip$/)
  })
})
