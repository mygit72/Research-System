import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useQuery } from '@tanstack/react-query'
import { History, Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useConversationSelection } from '@/hooks/useChat'
import { PAPER_SUGGESTIONS } from '@/lib/chat'
import { timeAgo } from '@/lib/format'
import { chatApi } from '@/services/api'
import { ChatPanel } from './ChatPanel'
import type { OpenSource } from './Sources'

const itemClass =
  'flex cursor-default flex-col items-start rounded-sm px-2 py-1.5 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

/** The assistant half of the paper split view: a chat limited to this one paper. */
export function PaperChat({
  documentId,
  conversationId,
  onConversation,
  onOpen,
  onClose,
  initialQuestion,
  initialQuestionKey,
}: {
  documentId: string
  conversationId: string | null
  onConversation: (id: string | null) => void
  onOpen: OpenSource
  onClose: () => void
  initialQuestion?: string | null
  initialQuestionKey?: string | number
}) {
  const history = useQuery({
    queryKey: ['chat', 'conversations', { documentId }],
    queryFn: () => chatApi.list({ documentId, singlePaper: true, limit: 50 }),
  })
  const others = history.data?.items ?? []
  const [selected, setSelected] = useConversationSelection(conversationId)
  const select = (next: string | null) => {
    setSelected(next)
    onConversation(next)
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-1 border-b border-border px-3">
        <h2 className="min-w-0 flex-1 truncate text-small font-semibold text-text">Ask anything</h2>
        {others.length > 0 && (
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Earlier chats about this paper">
                <History className="size-4" />
              </Button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content
                align="end"
                sideOffset={4}
                className="z-50 max-h-80 w-64 overflow-y-auto rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
              >
                {others.map((c) => (
                  <Dropdown.Item key={c.id} className={itemClass} onSelect={() => select(c.id)}>
                    <span className="w-full truncate font-medium">{c.title}</span>
                    <span className="text-caption text-subtle">{timeAgo(c.last_message_at ?? c.created_at)}</span>
                  </Dropdown.Item>
                ))}
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
        )}
        <Button variant="ghost" size="icon-sm" aria-label="New chat about this paper" onClick={() => select(null)}>
          <Plus className="size-4" />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Close chat" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        <ChatPanel
          compact
          conversationId={selected}
          documentIds={[documentId]}
          onCreated={select}
          onOpen={onOpen}
          placeholder="Ask anything…"
          emptyState={{
            title: 'Ask anything',
            description:
              'Ask about the paper or any other topic. Paper-specific claims cite its passages; general background is labeled separately. Follow up to go deeper.',
          }}
          suggestions={PAPER_SUGGESTIONS}
          initialQuestion={initialQuestion}
          initialQuestionKey={initialQuestionKey}
        />
      </div>
    </div>
  )
}
