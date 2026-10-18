import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowUp, Sparkles, Square } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { useChatSession } from '@/hooks/useChat'
import { fromLive, fromSaved } from '@/lib/chat'
import { cn } from '@/lib/cn'
import { systemApi } from '@/services/api'
import type { ChatMessage } from '@/types/api'
import { AssistantAnswer } from './Answer'
import type { OpenSource } from './Sources'

const MAX_LENGTH = 4000

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-lg rounded-br-sm bg-surface-muted px-3.5 py-2 text-body whitespace-pre-wrap text-text">
        {text}
      </p>
    </div>
  )
}

function AssistantRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary" aria-hidden>
        <Sparkles className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function SavedTurn({
  message,
  onOpen,
  onAnswerAgain,
}: {
  message: ChatMessage
  onOpen?: OpenSource
  onAnswerAgain?: () => void
}) {
  if (message.role === 'user') return <UserBubble text={message.content} />
  return (
    <AssistantRow>
      <AssistantAnswer view={fromSaved(message)} onOpen={onOpen} onAnswerAgain={onAnswerAgain} />
    </AssistantRow>
  )
}

export function Composer({
  onSend,
  onStop,
  busy,
  placeholder,
  autoFocus,
}: {
  onSend: (text: string) => void
  onStop: () => void
  busy: boolean
  placeholder: string
  autoFocus?: boolean
}) {
  const [text, setText] = useState('')
  const area = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [text])
  const send = () => {
    if (busy || !text.trim()) return
    onSend(text)
    setText('')
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        send()
      }}
      className="flex items-end gap-2 rounded-lg border border-border bg-surface p-2 shadow-sm focus-within:border-border-strong focus-within:ring-2 focus-within:ring-ring/30"
    >
      <label htmlFor="chat-input" className="sr-only">
        Your question
      </label>
      <textarea
        id="chat-input"
        ref={area}
        rows={1}
        value={text}
        maxLength={MAX_LENGTH}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            send()
          }
        }}
        className="max-h-[200px] min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-body text-text outline-none placeholder:text-subtle"
      />
      {busy ? (
        <Button type="button" variant="secondary" size="icon" onClick={onStop} aria-label="Stop answering">
          <Square className="size-3.5 fill-current" />
        </Button>
      ) : (
        <Button type="submit" size="icon" disabled={!text.trim()} aria-label="Send question">
          <ArrowUp className="size-4" />
        </Button>
      )}
    </form>
  )
}

function ModelBanner() {
  const status = useQuery({ queryKey: ['ai-status'], queryFn: systemApi.aiStatus, staleTime: 30_000 })
  const llm = status.data?.llm
  if (!llm || llm.ready) return null
  return (
    <div role="status" className="mb-3 flex gap-2.5 rounded-md border border-warning/30 bg-warning-soft p-3 text-small">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
      <div>
        <p className="font-medium text-text">
          {/* 'none': a site with a free shared model, and nothing chosen yet. */}
          {llm.source === 'none' ? llm.problem : <>The language model isn't ready. {llm.problem}</>}
        </p>
        {llm.hint && <p className="mt-0.5 text-caption text-muted">{llm.hint}</p>}
        {llm.source === 'none' && (
          <Link to="/settings" className="mt-0.5 inline-block text-caption text-primary underline underline-offset-2">
            Open Settings
          </Link>
        )}
        <p className="mt-0.5 text-caption text-muted">
          Search works without a model. Choose one to get chat answers and paper explanations.
        </p>
      </div>
    </div>
  )
}

/** Thread + composer for one conversation. Creates the conversation on the first question. */
export function ChatPanel({
  conversationId,
  documentIds,
  onCreated,
  onOpen,
  emptyState,
  suggestions,
  placeholder = 'Ask anything…',
  initialQuestion,
  initialQuestionKey,
  compact,
}: {
  conversationId: string | null
  documentIds?: string[]
  onCreated?: (id: string) => void
  onOpen?: OpenSource
  emptyState: { title: string; description: string }
  suggestions: string[]
  placeholder?: string
  /** A one-shot prompt supplied by a paper action, such as explaining a selected passage. */
  initialQuestion?: string | null
  initialQuestionKey?: string | number
  compact?: boolean
}) {
  const chat = useChatSession({ conversationId, documentIds, onCreated })
  const { ask: sendChat, busy: chatBusy } = chat
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true) // follow new text while the reader is at the bottom
  const sentInitialQuestion = useRef<string | null>(null)

  const liveText = chat.live?.text
  const count = chat.messages.length
  useEffect(() => {
    const el = scroller.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [liveText, chat.live?.stage, count])

  const ask = (text: string, fresh = false) => {
    pinned.current = true
    void chat.ask(text, { fresh })
  }

  useEffect(() => {
    const question = initialQuestion?.trim()
    const key = String(initialQuestionKey ?? question ?? '')
    if (!question || sentInitialQuestion.current === key || chatBusy) return
    sentInitialQuestion.current = key
    pinned.current = true
    void sendChat(question)
  }, [initialQuestion, initialQuestionKey, sendChat, chatBusy])

  const empty = !chat.live && count === 0
  const loading = !!conversationId && chat.detail.isPending && !chat.live

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
        }}
        className={cn('min-h-0 flex-1 overflow-y-auto', compact ? 'px-4 py-4' : 'px-4 py-6 sm:px-6')}
        aria-live="off"
      >
        <div className={cn('mx-auto space-y-6', !compact && 'max-w-3xl')}>
          {loading ? (
            <div className="space-y-4" aria-busy="true" aria-label="Loading conversation">
              <Skeleton className="ml-auto h-9 w-2/3" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : chat.detail.isError && !chat.live ? (
            <ErrorState error={chat.detail.error} title="We couldn't open this conversation" onRetry={() => chat.detail.refetch()} />
          ) : empty ? (
            <div className={cn('text-center', compact ? 'pt-6' : 'pt-[12vh]')}>
              <span className="mx-auto flex size-10 items-center justify-center rounded-full bg-primary-soft text-primary">
                <Sparkles className="size-5" aria-hidden />
              </span>
              <h2 className="mt-3 text-h3 text-text">{emptyState.title}</h2>
              <p className="mx-auto mt-1 max-w-md text-small text-muted">{emptyState.description}</p>
              <div className="mx-auto mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => ask(s)}
                    className="rounded-full border border-border bg-surface px-3 py-1.5 text-small text-muted shadow-sm transition-colors hover:border-border-strong hover:text-text"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {chat.messages.map((message, i) => {
                const question = chat.messages[i - 1]
                return (
                  <SavedTurn
                    key={message.id}
                    message={message}
                    onOpen={onOpen}
                    onAnswerAgain={
                      question?.role === 'user' && !chat.busy ? () => ask(question.content, true) : undefined
                    }
                  />
                )
              })}
              {chat.live && (
                <>
                  <UserBubble text={chat.live.question} />
                  <AssistantRow>
                    <AssistantAnswer
                      view={fromLive(chat.live)}
                      onOpen={onOpen}
                      onAnswerAgain={() => ask(chat.live!.question, true)}
                    />
                  </AssistantRow>
                </>
              )}
            </>
          )}
        </div>
      </div>
      <div className={cn('shrink-0 border-t border-border bg-bg', compact ? 'p-3' : 'px-4 pt-3 pb-4 sm:px-6')}>
        <div className={cn('mx-auto', !compact && 'max-w-3xl')}>
          <ModelBanner />
          <Composer onSend={ask} onStop={chat.stop} busy={chat.busy} placeholder={placeholder} autoFocus={!compact} />
          <p className="mt-1.5 text-center text-caption text-subtle">
            Ask about anything. Paper-specific claims cite sources; general background is labeled separately.
          </p>
        </div>
      </div>
    </div>
  )
}
