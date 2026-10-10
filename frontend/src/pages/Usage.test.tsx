import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usageApi } from '@/services/api'
import type { PerformanceSummary, UsageSummary } from '@/types/api'
import { UsagePage } from './UsagePage'

const today = new Date().toISOString().slice(0, 10)
const group = { errors: 0, latency_p50_ms: 40_000, latency_p95_ms: 90_000, first_token_p50_ms: 6000 }
const usage: UsageSummary = {
  days: 30,
  totals: { calls: 12, errors: 1, input_tokens: 24_000, output_tokens: 3000, cost_usd: 0.105, estimated_calls: 2, latency_p50_ms: 40_000, latency_p95_ms: 90_000 },
  by_feature: [
    { feature: 'chat', calls: 9, input_tokens: 18_000, output_tokens: 2000, cost_usd: 0.07, ...group, errors: 1 },
    { feature: 'summary', calls: 3, input_tokens: 6000, output_tokens: 1000, cost_usd: 0.035, ...group },
  ],
  by_model: [{ model: 'gpt-4.1', calls: 12, input_tokens: 24_000, output_tokens: 3000, cost_usd: 0.105, ...group }],
  by_day: [{ day: today, calls: 12, input_tokens: 24_000, output_tokens: 3000, cost_usd: 0.105 }],
  pricing: { default: [0, 0], models: { 'gpt-4.1': [5, 25] }, current_model: { model: 'gpt-4.1', input: 5, output: 25 } },
}
const performance: PerformanceSummary = {
  since: new Date(Date.now() - 3600_000).toISOString(),
  stages: [{ key: 'search_latency_ms', label: 'Search (total)', count: 40, mean_ms: 120, p50_ms: 60, p95_ms: 2100 }],
  caches: [{ name: 'rerank_scores', entries: 300, max_entries: 50_000, local_hits: 75, shared_hits: 5, misses: 20, hit_rate: 0.8, shared: true }],
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <UsagePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('UsagePage', () => {
  it('shows totals, a daily chart with its table, features, models, stages and caches', async () => {
    const summary = vi.spyOn(usageApi, 'summary').mockResolvedValue(usage)
    vi.spyOn(usageApi, 'performance').mockResolvedValue(performance)
    renderPage()
    expect(await screen.findByText('24,000 / 3,000')).toBeInTheDocument()
    expect(screen.getAllByText('$0.10').length).toBeGreaterThan(0)
    expect(screen.getByText('gpt-4.1: $5 / $25 per M tokens')).toBeInTheDocument()
    expect(screen.getByText('2 estimated (stopped early)')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Model calls per day/ })).toBeInTheDocument()
    const chat = screen.getByText('Research chat').closest('tr')!
    expect(within(chat).getByText('1 failed')).toBeInTheDocument()
    expect(within(chat).getByText('40 s')).toBeInTheDocument()
    const search = (await screen.findByText('Search (total)')).closest('tr')!
    expect(within(search).getByText('2.1 s')).toBeInTheDocument()
    const cache = screen.getByText('Reranker scores').closest('tr')!
    expect(within(cache).getByText('80%')).toBeInTheDocument()
    expect(within(cache).getByText('process + Redis')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '7 days' }))
    expect(summary).toHaveBeenLastCalledWith(7)
  })

  it('explains the empty state', async () => {
    vi.spyOn(usageApi, 'summary').mockResolvedValue({ ...usage, totals: { ...usage.totals, calls: 0 }, by_feature: [], by_model: [], by_day: [] })
    vi.spyOn(usageApi, 'performance').mockResolvedValue({ ...performance, stages: [] })
    renderPage()
    expect(await screen.findByText('No language-model calls yet')).toBeInTheDocument()
    expect(await screen.findByText('Nothing measured yet.')).toBeInTheDocument()
  })
})
