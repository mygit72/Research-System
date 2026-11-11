/**
 * Thin fetch wrapper for the backend API.
 *
 * - Attaches the in-memory access token.
 * - On 401, performs ONE shared refresh (single-flight, via the httpOnly
 *   refresh cookie) and retries the request once.
 * - Normalizes every failure into `ApiError` with a user-facing message.
 */
import type { ApiErrorBody, TokenResponse } from '@/types/api'

export const API_BASE = '/api/v1'

/**
 * Direct upload URL override for environments where proxying imposes payload limits
 * (such as Vercel's 4.5 MB edge ceiling). When VITE_API_DIRECT_URL is set (e.g.
 * https://api.yourdomain.com), large uploads go directly to the backend over HTTPS
 * with the in-memory Authorization Bearer token, bypassing the proxy.
 * If unset, defaults to API_BASE (/api/v1) for same-origin proxy setups.
 */
export const UPLOAD_BASE = (import.meta.env.VITE_API_DIRECT_URL as string | undefined)?.replace(/\/$/, '')
  ? `${(import.meta.env.VITE_API_DIRECT_URL as string).replace(/\/$/, '')}/api/v1`
  : API_BASE

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly hint: string | null
  readonly requestId: string | null
  readonly fieldErrors: Record<string, string>

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.hint = body.hint ?? null
    this.requestId = body.request_id ?? null
    this.fieldErrors = Object.fromEntries(
      (body.details?.fields ?? []).map((f) => [f.field, f.message]),
    )
  }
}

interface TokenHooks {
  getAccessToken: () => string | null
  onTokens: (tokens: TokenResponse) => void
  onSessionExpired: () => void
}

let hooks: TokenHooks = {
  getAccessToken: () => null,
  onTokens: () => {},
  onSessionExpired: () => {},
}

export function configureAuth(next: TokenHooks) {
  hooks = next
}

let refreshInFlight: Promise<TokenResponse | null> | null = null

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<TokenResponse | null> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'same-origin',
      })
      if (!response.ok) return null
      const tokens = (await response.json()) as TokenResponse
      hooks.onTokens(tokens)
      return tokens
    } catch {
      return null
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const data = (await response.json()) as { error?: ApiErrorBody }
    if (data.error) return new ApiError(response.status, data.error)
  } catch {
    /* non-JSON body (proxy error, HTML page) */
  }
  const fallback: Record<number, string> = {
    502: 'The server is not reachable right now.',
    503: 'The service is temporarily unavailable.',
    504: 'The server took too long to respond.',
  }
  return new ApiError(response.status, {
    code: 'http_error',
    message: fallback[response.status] ?? 'Something went wrong. Please try again.',
  })
}

type Body = Record<string, unknown> | unknown[] | FormData | undefined

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: Body
  signal?: AbortSignal
  /** Skip the automatic refresh-and-retry (used by auth endpoints themselves). */
  noRetry?: boolean
  /** Return the body as text (downloads such as BibTeX) instead of parsing JSON. */
  raw?: boolean
  /** Return the body as a Blob (binary downloads: Word, PDF). */
  blob?: boolean
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const send = () => {
    const headers: Record<string, string> = {}
    const token = hooks.getAccessToken()
    if (token) headers.Authorization = `Bearer ${token}`
    let body: BodyInit | undefined
    if (options.body instanceof FormData) body = options.body
    else if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(options.body)
    }
    return fetch(`${API_BASE}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
      credentials: 'same-origin',
    })
  }

  let response: Response
  try {
    response = await send()
    if (response.status === 401 && !options.noRetry) {
      const refreshed = await refreshSession()
      if (!refreshed) {
        hooks.onSessionExpired()
        throw await parseError(response)
      }
      response = await send()
    }
  } catch (error) {
    if (error instanceof ApiError || (error instanceof DOMException && error.name === 'AbortError'))
      throw error
    throw new ApiError(0, {
      code: 'network_error',
      message: "We couldn't reach the server.",
      hint: 'Check your connection and that the backend is running.',
    })
  }

  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  if (options.raw) return (await response.text()) as T
  if (options.blob) return (await response.blob()) as T
  return (await response.json()) as T
}

/**
 * Multipart upload with progress events (fetch can't report upload progress).
 * Shares auth handling with `request`: one refresh + retry on 401.
 */
export function uploadWithProgress<T>(
  path: string,
  form: FormData,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  const attempt = (retried: boolean): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${UPLOAD_BASE}${path}`)
      const token = hooks.getAccessToken()
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total)
      }
      xhr.onerror = () =>
        reject(
          new ApiError(0, {
            code: 'network_error',
            message: "We couldn't reach the server.",
            hint: 'Check your connection and try again.',
          }),
        )
      xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
      xhr.onload = async () => {
        if (xhr.status === 401 && !retried) {
          const refreshed = await refreshSession()
          if (!refreshed) {
            hooks.onSessionExpired()
          } else {
            attempt(true).then(resolve, reject)
            return
          }
        }
        const response = new Response(xhr.responseText || null, {
          status: xhr.status,
          headers: { 'Content-Type': 'application/json' },
        })
        if (!response.ok) {
          reject(await parseError(response))
          return
        }
        resolve((await response.json()) as T)
      }
      signal?.addEventListener('abort', () => xhr.abort(), { once: true })
      xhr.send(form)
    })
  return attempt(false)
}

/** Parse server-sent events: returns complete `data:` payloads and the unfinished remainder. */
export function parseSSE(buffer: string): { events: unknown[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: unknown[] = []
  for (const block of blocks) {
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).replace(/^ /, ''))
      .join('\n')
    if (data) events.push(JSON.parse(data))
  }
  return { events, rest }
}

/**
 * POST that streams server-sent events back (EventSource can't send a body or auth header).
 * Errors before the stream starts are thrown as `ApiError`, like `request`.
 */
export async function streamRequest<E>(
  path: string,
  body: Record<string, unknown>,
  onEvent: (event: E) => void,
  signal?: AbortSignal,
): Promise<void> {
  const send = () => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }
    const token = hooks.getAccessToken()
    if (token) headers.Authorization = `Bearer ${token}`
    return fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
      credentials: 'same-origin',
    })
  }

  let response: Response
  try {
    response = await send()
    if (response.status === 401) {
      const refreshed = await refreshSession()
      if (!refreshed) {
        hooks.onSessionExpired()
        throw await parseError(response)
      }
      response = await send()
    }
  } catch (error) {
    if (error instanceof ApiError || (error instanceof DOMException && error.name === 'AbortError'))
      throw error
    throw new ApiError(0, {
      code: 'network_error',
      message: "We couldn't reach the server.",
      hint: 'Check your connection and that the backend is running.',
    })
  }
  if (!response.ok) throw await parseError(response)
  if (!response.body) throw new ApiError(0, { code: 'stream_error', message: 'The answer stream was empty.' })

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parseSSE(buffer)
      buffer = parsed.rest
      for (const event of parsed.events) onEvent(event as E)
    }
    const tail = parseSSE(buffer + decoder.decode() + '\n\n')
    for (const event of tail.events) onEvent(event as E)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    throw new ApiError(0, {
      code: 'stream_error',
      message: 'The connection was interrupted while the answer was streaming.',
      hint: 'The partial answer was saved. Try asking again.',
    })
  } finally {
    reader.releaseLock()
  }
}
