import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { reportsApi } from '@/services/api'
import type { Report } from '@/types/api'
import { useReport } from './useReports'

afterEach(() => vi.restoreAllMocks())

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
)

describe('useReport', () => {
  it('requests nothing without an id (an empty id would hit the list route and its redirect)', async () => {
    const get = vi.spyOn(reportsApi, 'get')
    const { result } = renderHook(() => useReport(''), { wrapper })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(get).not.toHaveBeenCalled()
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('loads the report when there is an id', async () => {
    const get = vi.spyOn(reportsApi, 'get').mockResolvedValue({ id: 'r1', status: 'ready' } as Report)
    const { result } = renderHook(() => useReport('r1'), { wrapper })
    await waitFor(() => expect(result.current.data?.id).toBe('r1'))
    expect(get).toHaveBeenCalledWith('r1')
  })
})
