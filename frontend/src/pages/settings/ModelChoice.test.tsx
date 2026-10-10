import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { modelApi } from '@/services/api'
import type { FreeTier, ModelChoiceView, ModelPreset } from '@/types/api'
import { ModelChoice } from './ModelChoice'

function preset(id: string, label: string, extra: Partial<ModelPreset> = {}): ModelPreset {
  return {
    id,
    label,
    provider: 'openai',
    base_url: `https://${id}.example/v1`,
    keys_url: `https://${id}.example/keys`,
    note: `${label} note.`,
    local: false,
    needs_key: true,
    available: true,
    ...extra,
  }
}

function view(overrides: Partial<ModelChoiceView> = {}, allowLocal = true): ModelChoiceView {
  return {
    choice: null,
    server_default: { provider: 'ollama', model: 'qwen2.5:3b' },
    free_tier: null,
    download_url: '',
    options: {
      allow_user_api_keys: true,
      allow_local_models: allowLocal,
      presets: [
        preset('openai', 'OpenAI'),
        preset('groq', 'Groq'),
        preset('ollama', 'Ollama (a model on your computer)', {
          provider: 'ollama',
          base_url: 'http://localhost:11434',
          local: true,
          needs_key: false,
          available: allowLocal,
        }),
      ],
    },
    status: { provider: 'ollama', model: 'qwen2.5:3b', remote: false, ready: true, source: 'server' },
    ...overrides,
  }
}

const NEMOTRON = 'nvidia/nemotron-3-ultra-550b-a55b:free'

/** A public site whose model is a shared free one: no local models, nothing chosen yet. */
function freeSite(free: Partial<FreeTier> = {}, overrides: Partial<ModelChoiceView> = {}): ModelChoiceView {
  const chosen = free.chosen ?? false
  return view(
    {
      server_default: { provider: 'openai', model: NEMOTRON },
      free_tier: {
        label: 'Nemotron 3 Ultra (free)',
        model: NEMOTRON,
        host: 'NVIDIA, through OpenRouter',
        chosen,
        daily_limit: 50,
        used_today: 8,
        remaining_today: 42,
        resets_at: '2026-10-11T00:00:00Z',
        ...free,
      },
      choice: chosen
        ? { preset: 'free', label: 'Nemotron 3 Ultra (free)', model: NEMOTRON, base_url: '', has_key: false, key_hint: '', updated_at: '2026-10-10T12:00:00Z' }
        : null,
      status: chosen
        ? { provider: 'openai', model: NEMOTRON, remote: true, ready: true, source: 'free' }
        : { provider: 'openai', model: NEMOTRON, remote: true, ready: false, source: 'none', problem: 'Choose how to run the AI features first.' },
      ...overrides,
    },
    false,
  )
}

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ModelChoice />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Settings → your model', () => {
  it("uses the server's model until you choose", async () => {
    vi.spyOn(modelApi, 'get').mockResolvedValue(view())
    renderIt()
    expect(await screen.findByText('qwen2.5:3b')).toBeInTheDocument()
    expect(screen.getByText('In use')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /This server's model/ })).toHaveAttribute('aria-checked', 'true')
  })

  it('tests a key, lists its models and saves the choice', async () => {
    vi.spyOn(modelApi, 'get').mockResolvedValue(view())
    const test = vi.spyOn(modelApi, 'test').mockResolvedValue({
      ok: true,
      models: ['llama-3.3-70b', 'qwen-qwq-32b'],
      message: 'Connected: 2 model(s) available.',
    })
    const saved = view({
      choice: {
        preset: 'groq',
        label: 'Groq',
        model: 'llama-3.3-70b',
        base_url: 'https://groq.example/v1',
        has_key: true,
        key_hint: '…WXYZ',
        updated_at: '2026-10-09T12:00:00Z',
      },
    })
    const save = vi.spyOn(modelApi, 'save').mockResolvedValue(saved)
    renderIt()
    await userEvent.click(await screen.findByRole('radio', { name: /My own API key/ }))
    await userEvent.selectOptions(screen.getByLabelText('Provider'), 'groq')
    expect(screen.getByRole('link', { name: /Get a key/ })).toHaveAttribute('href', 'https://groq.example/keys')
    const key = screen.getByLabelText('Groq API key')
    expect(key).toHaveAttribute('type', 'password')
    await userEvent.type(key, 'gsk_secret_key_WXYZ')
    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Connected: 2 model(s) available.')
    expect(test).toHaveBeenCalledWith({ preset: 'groq', base_url: undefined, api_key: 'gsk_secret_key_WXYZ' })
    await userEvent.type(screen.getByLabelText('Model'), 'llama-3.3-70b')
    await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        preset: 'groq',
        model: 'llama-3.3-70b',
        base_url: undefined,
        api_key: 'gsk_secret_key_WXYZ',
      }),
    )
    // After saving, the form starts again from what was saved: the key field is empty.
    expect(await screen.findByPlaceholderText(/Saved key …WXYZ/)).toHaveValue('')
  })

  it('keeps a saved key when it is left empty, and can go back to the server model', async () => {
    const saved = view({
      choice: {
        preset: 'groq',
        label: 'Groq',
        model: 'llama-3.3-70b',
        base_url: 'https://groq.example/v1',
        has_key: true,
        key_hint: '…WXYZ',
        updated_at: '2026-10-09T12:00:00Z',
      },
    })
    vi.spyOn(modelApi, 'get').mockResolvedValue(saved)
    const save = vi.spyOn(modelApi, 'save').mockResolvedValue(saved)
    const reset = vi.spyOn(modelApi, 'reset').mockResolvedValue(view())
    renderIt()
    const model = await screen.findByLabelText('Model')
    await userEvent.clear(model)
    await userEvent.type(model, 'qwen-qwq-32b')
    await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
    await waitFor(() => expect(save).toHaveBeenCalled())
    expect(save.mock.calls[0][0].api_key).toBeUndefined()

    await userEvent.click(screen.getByRole('radio', { name: /This server's model/ }))
    await userEvent.click(screen.getByRole('button', { name: "Use this server's model" }))
    await waitFor(() => expect(reset).toHaveBeenCalled())
    expect(await screen.findByText('In use')).toBeInTheDocument()
  })

  it('offers a local model with its address, and explains when the server cannot', async () => {
    vi.spyOn(modelApi, 'get').mockResolvedValue(view())
    const test = vi.spyOn(modelApi, 'test').mockResolvedValue({
      ok: true,
      models: ['llama3.2:3b'],
      message: 'Connected: 1 model(s) available.',
    })
    const { unmount } = renderIt()
    await userEvent.click(await screen.findByRole('radio', { name: /A model on my computer/ }))
    expect(screen.getByLabelText('Address')).toHaveValue('http://localhost:11434')
    expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    await waitFor(() =>
      expect(test).toHaveBeenCalledWith({ preset: 'ollama', base_url: 'http://localhost:11434', api_key: undefined }),
    )
    expect(screen.getByLabelText('Model')).toHaveValue('llama3.2:3b') // the only one: picked
    unmount()

    // A public server can't reach a model on someone's computer: it explains their own copy.
    vi.spyOn(modelApi, 'get').mockResolvedValue(view({ download_url: 'https://example.org/app.zip' }, false))
    renderIt()
    await userEvent.click(await screen.findByRole('radio', { name: /Run it on my computer/ }))
    expect(screen.getByText(/never\s+leave it/)).toBeInTheDocument()
    expect(screen.getByText(/run-local\.ps1/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Download the app/ })).toHaveAttribute('href', 'https://example.org/app.zip')
    expect(screen.queryByLabelText('Address')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Use this model' })).not.toBeInTheDocument()
  })

  it('offers the free shared model with what it costs, and uses it only once chosen', async () => {
    vi.spyOn(modelApi, 'get').mockResolvedValue(freeSite())
    const save = vi.spyOn(modelApi, 'save').mockResolvedValue(freeSite({ chosen: true }))
    renderIt()
    expect(await screen.findByRole('radio', { name: /Free shared model/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByText('In use')).not.toBeInTheDocument()
    // Slower, limited, and hosted elsewhere: said before the choice, not after.
    expect(screen.getByText(/Free, and slower/)).toBeInTheDocument()
    expect(screen.getByText(/42 of 50 requests left today/)).toBeInTheDocument()
    expect(screen.getByText(/It runs at NVIDIA, through OpenRouter, not on this site/)).toBeInTheDocument()
    expect(screen.getByText(/a free service may keep what it\s+receives/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Use the free model' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith({ preset: 'free', model: '' }))
    expect(await screen.findByText('In use')).toBeInTheDocument()
  })

  it('can stop using the free model, and warns that choosing it deletes a saved key', async () => {
    vi.spyOn(modelApi, 'get').mockResolvedValue(freeSite({ chosen: true }))
    const reset = vi.spyOn(modelApi, 'reset').mockResolvedValue(freeSite())
    const { unmount } = renderIt()
    await userEvent.click(await screen.findByRole('button', { name: 'Stop using it' }))
    await waitFor(() => expect(reset).toHaveBeenCalled())
    expect(await screen.findByRole('button', { name: 'Use the free model' })).toBeInTheDocument()
    unmount()

    const withKey = freeSite({}, {
      choice: { preset: 'groq', label: 'Groq', model: 'llama-3.3-70b', base_url: 'https://groq.example/v1', has_key: true, key_hint: '…WXYZ', updated_at: '2026-10-09T12:00:00Z' },
    })
    vi.spyOn(modelApi, 'get').mockResolvedValue(withKey)
    renderIt()
    await userEvent.click(await screen.findByRole('radio', { name: /Free shared model/ }))
    expect(screen.getByRole('button', { name: 'Use the free model (deletes my saved key)' })).toBeInTheDocument()
  })
})
