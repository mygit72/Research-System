import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { chatApi } from '@/services/api'
import { ApiError } from '@/services/http'
import type {
  ChatEvent,
  ChatStage,
  EvidenceItem,
  QueryAnalysis,
  ReusedFrom,
  Verification,
} from '@/types/api'

/** The answer being streamed right now (before it is saved and refetched). */
export interface LiveTurn {
  question: string
  /** Messages in the conversation before this turn; the live turn hides once it's saved. */
  baseCount: number
  state: 'streaming' | 'done' | 'stopped' | 'error'
  stage: ChatStage | null
  stageDetail: string
  analysis: QueryAnalysis | null
  evidence: EvidenceItem[] | null
  reranker: string | null
  text: string
  invalidCitations: number[]
  verification: Verification | null
  reused: ReusedFrom | null
  error: { message: string; hint: string | null } | null
}

export const conversationKey = (id: string) => ['chat', 'conversation', id] as const

export function applyEvent(turn: LiveTurn, event: ChatEvent): LiveTurn {
  switch (event.type) {
    case 'status':
      return { ...turn, stage: event.stage, stageDetail: event.detail }
    case 'query':
      return { ...turn, analysis: event.analysis }
    case 'evidence':
      return { ...turn, evidence: event.items, reranker: event.reranker }
    case 'token':
      return { ...turn, text: turn.text + event.text }
    case 'answer':
      // The server's cleaned text: invented citation numbers are removed.
      return { ...turn, text: event.text, invalidCitations: event.invalid_citations }
    case 'verification': {
      const { type: _type, ...verification } = event
      return { ...turn, verification }
    }
    case 'reused': {
      const { type: _type, ...reused } = event
      return { ...turn, reused }
    }
    case 'error':
      return { ...turn, state: 'error', error: { message: event.message, hint: event.hint } }
    case 'done':
      return { ...turn, state: turn.state === 'error' ? 'error' : 'done', stage: null }
  }
}

interface Options {
  conversationId: string | null
  /** Papers a new conversation is limited to (paper chat). */
  documentIds?: string[]
  /** Called when the first question creates the conversation. */
  onCreated?: (id: string) => void
}

export function useChatSession({ conversationId, documentIds, onCreated }: Options) {
  const detail = useQuery({
    queryKey: conversationKey(conversationId ?? 'none'),
    queryFn: () => chatApi.get(conversationId!),
    enabled: !!conversationId,
  })
  const queryClient = useQueryClient()
  const [live, setLive] = useState<LiveTurn | null>(null)
  const controller = useRef<AbortController | null>(null)
  const ownId = useRef<string | null>(null) // conversation this session created or is streaming to

  // Switching to another conversation drops the previous live turn (its stream is stopped).
  useEffect(() => {
    if (conversationId && conversationId === ownId.current) return
    controller.current?.abort()
    controller.current = null
    ownId.current = conversationId
    setLive(null)
  }, [conversationId])

  useEffect(() => () => controller.current?.abort(), [])

  const messages = detail.data?.messages ?? []
  // Once the saved conversation contains this turn's answer, show that instead. Failed
  // turns stay live: they carry the hint ("Run: ollama pull …") the saved copy doesn't.
  const replaced =
    !!live &&
    (live.state === 'done' || live.state === 'stopped') &&
    messages.length >= live.baseCount + 2
  const shown = replaced ? null : live

  const refresh = useCallback(async (id: string) => {
    await queryClient.invalidateQueries({ queryKey: conversationKey(id) })
    void queryClient.invalidateQueries({ queryKey: ['chat', 'conversations'] })
  }, [queryClient])

  const ask = useCallback(
    async (question: string, options: { fresh?: boolean } = {}) => {
      const text = question.trim()
      if (!text || controller.current) return
      const abort = new AbortController()
      controller.current = abort
      const baseCount = detail.data?.messages.length ?? 0
      let turn: LiveTurn = {
        question: text,
        baseCount,
        state: 'streaming',
        stage: 'understanding',
        stageDetail: 'Understanding the question',
        analysis: null,
        evidence: null,
        reranker: null,
        text: '',
        invalidCitations: [],
        verification: null,
        reused: null,
        error: null,
      }
      setLive(turn)
      let id = conversationId
      try {
        if (!id) {
          const created = await chatApi.create({ document_ids: documentIds })
          id = created.id
          ownId.current = id
          queryClient.setQueryData(conversationKey(id), { ...created, messages: [] })
          onCreated?.(id)
        }
        await chatApi.ask(
          id,
          text,
          (event) => {
            turn = applyEvent(turn, event)
            setLive(turn)
          },
          abort.signal,
          options.fresh,
        )
        if (turn.state === 'streaming') turn = { ...turn, state: 'done', stage: null }
        setLive(turn)
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          turn = { ...turn, state: 'stopped', stage: null }
        } else {
          const apiError = error instanceof ApiError ? error : null
          turn = {
            ...turn,
            state: 'error',
            stage: null,
            error: {
              message: apiError?.message ?? 'Something went wrong while answering.',
              hint: apiError?.hint ?? null,
            },
          }
        }
        setLive(turn)
      } finally {
        if (controller.current === abort) controller.current = null
      }
      if (id) {
        await refresh(id)
        // A stopped answer is saved by the server just after the connection closes.
        if (turn.state === 'stopped') window.setTimeout(() => void refresh(id), 800)
      }
    },
    [conversationId, detail.data?.messages.length, documentIds, onCreated, queryClient, refresh],
  )

  const stop = useCallback(() => controller.current?.abort(), [])

  return {
    detail,
    // While a turn is live, saved messages from that turn (e.g. the question, after a
    // background refetch) are hidden so nothing shows twice.
    messages: shown ? messages.slice(0, shown.baseCount) : messages,
    live: shown,
    busy: live?.state === 'streaming',
    ask,
    stop,
  }
}

/**
 * The conversation on screen. User actions update it at once; it also follows the URL
 * (back/forward, links). Reading it only from the URL lagged behind: URL updates commit in a
 * transition, so a question sent right after "New chat" went to the previous conversation.
 */
export function useConversationSelection(fromUrl: string | null) {
  const [selected, setSelected] = useState(fromUrl)
  const [seen, setSeen] = useState(fromUrl)
  if (fromUrl !== seen) {
    setSeen(fromUrl)
    setSelected(fromUrl)
  }
  return [selected, setSelected] as const
}
