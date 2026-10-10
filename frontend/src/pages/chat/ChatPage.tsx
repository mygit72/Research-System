import { useState } from 'react'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, History, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState, Skeleton } from '@/components/ui/Feedback'
import { Input } from '@/components/ui/Input'
import { Sheet } from '@/components/ui/Sheet'
import { conversationKey, useConversationSelection } from '@/hooks/useChat'
import { LIBRARY_SUGGESTIONS } from '@/lib/chat'
import { cn } from '@/lib/cn'
import { timeAgo } from '@/lib/format'
import { chatApi } from '@/services/api'
import type { Conversation } from '@/types/api'

const itemClass =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'

function ConversationActions({ conversation, onDeleted }: { conversation: Conversation; onDeleted: () => void }) {
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [title, setTitle] = useState(conversation.title)
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['chat'] })
  const rename = useMutation({
    mutationFn: () => chatApi.rename(conversation.id, title.trim()),
    onSuccess: () => {
      setRenaming(false)
      void invalidate()
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => chatApi.remove(conversation.id),
    onSuccess: () => {
      setDeleting(false)
      queryClient.removeQueries({ queryKey: conversationKey(conversation.id) })
      void invalidate()
      toast.success('Conversation deleted')
      onDeleted()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <button
            type="button"
            aria-label={`Actions for ${conversation.title}`}
            className="rounded-sm p-1 text-subtle opacity-0 group-hover:opacity-100 hover:bg-surface-muted hover:text-text focus-visible:opacity-100 data-[state=open]:opacity-100"
          >
            <MoreHorizontal className="size-4" />
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content
            align="end"
            sideOffset={4}
            className="z-50 w-44 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
          >
            <Dropdown.Item className={itemClass} onSelect={() => setRenaming(true)}>
              <Pencil className="size-4 text-muted" /> Rename
            </Dropdown.Item>
            <Dropdown.Item className={`${itemClass} text-error`} onSelect={() => setDeleting(true)}>
              <Trash2 className="size-4" /> Delete
            </Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
      <Dialog open={renaming} onOpenChange={setRenaming} title="Rename conversation">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (title.trim()) rename.mutate()
          }}
          className="space-y-4"
        >
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} aria-label="Title" autoFocus />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setRenaming(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={rename.isPending} disabled={!title.trim()}>
              Save
            </Button>
          </div>
        </form>
      </Dialog>
      <Dialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Delete this conversation?"
        description="Its questions, answers and citations will be permanently removed. Your papers are not affected."
      >
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setDeleting(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => remove.mutate()} loading={remove.isPending}>
            Delete
          </Button>
        </div>
      </Dialog>
    </>
  )
}

function ConversationList({
  activeId,
  onNavigate,
}: {
  activeId: string | null
  onNavigate: (id: string) => void
}) {
  const navigate = useNavigate()
  const list = useQuery({ queryKey: ['chat', 'conversations'], queryFn: () => chatApi.list({ limit: 200 }) })
  if (list.isPending)
    return (
      <div className="space-y-2 p-1" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />
  if (list.data.items.length === 0)
    return <p className="px-2 py-3 text-small text-muted">Your conversations will appear here.</p>
  return (
    <ul className="space-y-0.5">
      {list.data.items.map((c) => (
        <li key={c.id} className="group relative">
          <Link
            to={`/chat/${c.id}`}
            onClick={() => onNavigate(c.id)}
            aria-current={c.id === activeId ? 'page' : undefined}
            className={cn(
              'block rounded-md py-2 pr-8 pl-2.5 transition-colors',
              c.id === activeId ? 'bg-surface-muted text-text' : 'text-muted hover:bg-surface-muted/60 hover:text-text',
            )}
          >
            <span className="block truncate text-small font-medium">{c.title}</span>
            <span className="flex items-center gap-1.5 text-caption text-subtle">
              {c.scope === 'papers' && <BookOpen className="size-3" aria-label="About specific papers" />}
              {timeAgo(c.last_message_at ?? c.created_at)}
            </span>
          </Link>
          <span className="absolute top-2 right-1.5">
            <ConversationActions
              conversation={c}
              onDeleted={() => {
                if (c.id === activeId) navigate('/chat', { replace: true })
              }}
            />
          </span>
        </li>
      ))}
    </ul>
  )
}

export function ChatPage() {
  const { id: fromUrl = null } = useParams()
  const [id, setId] = useConversationSelection(fromUrl)
  const navigate = useNavigate()
  const [historyOpen, setHistoryOpen] = useState(false)
  const conversation = useQuery({
    queryKey: ['chat', 'conversations'],
    queryFn: () => chatApi.list({ limit: 200 }),
    select: (page) => page.items.find((c) => c.id === id) ?? null,
    enabled: !!id,
  }).data

  const newChat = () => {
    setId(null)
    navigate('/chat')
  }
  return (
    <div className="flex h-[calc(100dvh-3.5rem)] min-h-0">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-border lg:flex" aria-label="Conversations">
        <div className="p-3">
          <Button variant="secondary" className="w-full justify-start" onClick={newChat}>
            <Plus className="size-4" aria-hidden /> New chat
          </Button>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          <ConversationList activeId={id} onNavigate={setId} />
        </nav>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Research chat">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4 sm:px-6">
          <Button variant="ghost" size="icon-sm" className="lg:hidden" aria-label="Conversation history" onClick={() => setHistoryOpen(true)}>
            <History className="size-4" />
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-small font-semibold text-text">
            {conversation?.title ?? 'Research Assistant'}
            <span className="ml-2 font-normal text-muted">
              {conversation?.scope === 'papers'
                ? `· ${conversation.document_ids.length} paper${conversation.document_ids.length === 1 ? '' : 's'}`
                : '· Searching your research library'}
            </span>
          </h1>
          {conversation?.scope === 'papers' && conversation.document_ids.length === 1 && (
            <Link to={`/papers/${conversation.document_ids[0]}?chat=${conversation.id}`} className="hidden text-small text-primary hover:underline sm:inline">
              Open with paper
            </Link>
          )}
          <Button variant="ghost" size="sm" className="lg:hidden" onClick={newChat}>
            <Plus className="size-4" aria-hidden /> New
          </Button>
        </div>
        <div className="min-h-0 flex-1">
          <ChatPanel
            conversationId={id}
            documentIds={conversation?.document_ids}
            onCreated={(created) => {
              setId(created)
              navigate(`/chat/${created}`, { replace: true })
            }}
            emptyState={{
              title: 'Ask your research library',
              description:
                'Answers are written only from passages in your papers, with a numbered citation for every claim. Click a citation to see the source.',
            }}
            suggestions={LIBRARY_SUGGESTIONS}
          />
        </div>
      </section>
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen} title="Conversations" side="left">
        <ConversationList
          activeId={id}
          onNavigate={(selected) => {
            setId(selected)
            setHistoryOpen(false)
          }}
        />
      </Sheet>
    </div>
  )
}
