import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, configureAuth, parseSSE, request, streamRequest } from './http'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('request()', () => {
  let token: string | null
  const onSessionExpired = vi.fn()

  beforeEach(() => {
    token = 'old'
    onSessionExpired.mockReset()
    configureAuth({
      getAccessToken: () => token,
      onTokens: (t) => {
        token = t.access_token
      },
      onSessionExpired,
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sends the bearer token and parses JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(request('/thing')).resolves.toEqual({ ok: true })
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer old')
  })

  it('refreshes once for concurrent 401s, then retries each request', async () => {
    let refreshCalls = 0
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith('/auth/refresh')) {
        refreshCalls += 1
        return json(200, { access_token: 'new', refresh_token: 'r', expires_at: '' })
      }
      const auth = (init.headers as Record<string, string>).Authorization
      return auth === 'Bearer new' ? json(200, { ok: url }) : json(401, { error: { code: 'unauthenticated', message: 'expired' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    const results = await Promise.all([request('/a'), request('/b'), request('/c')])
    expect(results).toEqual([{ ok: '/api/v1/a' }, { ok: '/api/v1/b' }, { ok: '/api/v1/c' }])
    expect(refreshCalls).toBe(1)
  })

  it('signals session expiry when the refresh fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(401, { error: { code: 'unauthenticated', message: 'Please sign in.' } })),
    )
    await expect(request('/a')).rejects.toMatchObject({ status: 401, message: 'Please sign in.' })
    expect(onSessionExpired).toHaveBeenCalledOnce()
  })

  it('exposes user-facing error details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        json(422, {
          error: {
            code: 'validation_error',
            message: 'Password too short',
            hint: 'Use 10+ characters',
            request_id: 'req-1',
            details: { fields: [{ field: 'password', message: 'Password too short' }] },
          },
        }),
      ),
    )
    const error = (await request('/a').catch((e) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.hint).toBe('Use 10+ characters')
    expect(error.requestId).toBe('req-1')
    expect(error.fieldErrors).toEqual({ password: 'Password too short' })
  })

  it('turns network failures into a friendly error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(request('/a')).rejects.toMatchObject({
      code: 'network_error',
      message: "We couldn't reach the server.",
    })
  })

  it('falls back to a readable message for non-JSON gateway errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 502 })))
    await expect(request('/a')).rejects.toMatchObject({
      message: 'The server is not reachable right now.',
    })
  })
})

describe('server-sent events', () => {
  it('parses complete events and keeps the unfinished rest', () => {
    const { events, rest } = parseSSE('data: {"a":1}\n\ndata: {"b":2}\r\n\r\ndata: {"c"')
    expect(events).toEqual([{ a: 1 }, { b: 2 }])
    expect(rest).toBe('data: {"c"')
  })

  it('streams events split across network chunks, with auth', async () => {
    const encoder = new TextEncoder()
    const chunks = ['data: {"type":"tok', 'en","text":"Lo"}\n\nda', 'ta: {"type":"done"}\n\n']
    const body = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    configureAuth({ getAccessToken: () => 'tok', onTokens: () => {}, onSessionExpired: () => {} })
    const seen: unknown[] = []
    await streamRequest('/chat/x/messages', { content: 'q' }, (e) => seen.push(e))
    expect(seen).toEqual([{ type: 'token', text: 'Lo' }, { type: 'done' }])
    const init = fetchMock.mock.calls[0][1]
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(JSON.parse(init.body)).toEqual({ content: 'q' })
    vi.unstubAllGlobals()
  })

  it('reports errors before the stream starts as ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(json(404, { error: { code: 'not_found', message: 'Conversation not found.' } })),
    )
    await expect(streamRequest('/chat/x/messages', { content: 'q' }, () => {})).rejects.toThrow(
      'Conversation not found.',
    )
    vi.unstubAllGlobals()
  })
})
