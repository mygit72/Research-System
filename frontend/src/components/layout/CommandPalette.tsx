import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Command } from 'cmdk'
import * as RadixDialog from '@radix-ui/react-dialog'
import { FileText, FolderPlus, Moon, Search, Sun, TextSearch, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { CollectionDialog } from '@/components/organization/Collections'
import { usePreferenceSync } from '@/hooks/usePreferenceSync'
import { allNav } from '@/lib/navigation'
import { documentsApi } from '@/services/api'
import { useUploads } from '@/stores/uploads'
import { resolveTheme, usePreferences } from '@/stores/preferences'
import { useUI } from '@/stores/ui'

const itemClass =
  'flex h-10 cursor-default items-center gap-3 rounded-md px-3 text-small text-text data-[selected=true]:bg-surface-muted'

/**
 * ⌘K / Ctrl+K palette: full-text passage search, papers, navigation and quick actions. Later phases add
 * result groups for papers, authors, datasets, notes and conversations.
 */
export function CommandPalette() {
  const open = useUI((s) => s.commandOpen)
  const setOpen = useUI((s) => s.setCommandOpen)
  const navigate = useNavigate()
  const theme = usePreferences((s) => s.theme)
  const setTheme = usePreferences((s) => s.setTheme)
  const sync = usePreferenceSync()
  const openUpload = useUploads((s) => s.setDialogOpen)
  const [search, setSearch] = useState('')
  const [creatingCollection, setCreatingCollection] = useState(false)
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const id = setTimeout(() => setDebounced(search.trim()), 200)
    return () => clearTimeout(id)
  }, [search])
  const papers = useQuery({
    queryKey: ['documents', 'list', { q: debounced, limit: 8, palette: true }],
    queryFn: () => documentsApi.list({ q: debounced, limit: 8 }),
    enabled: open && debounced.length >= 2,
  })

  const run = (action: () => void) => {
    setOpen(false)
    action()
  }
  const isDark = resolveTheme(theme) === 'dark'

  return (
    <>
      <RadixDialog.Root
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (!next) setSearch('')
        }}
      >
        <RadixDialog.Portal>
          <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/40 animate-fade-in" />
          <RadixDialog.Content className="fixed top-[12vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-surface-elevated shadow-lg animate-fade-in">
            <RadixDialog.Title className="sr-only">Command palette</RadixDialog.Title>
            <RadixDialog.Description className="sr-only">
              Search pages and run quick actions
            </RadixDialog.Description>
            <Command label="Command palette" loop>
              <div className="flex items-center gap-3 border-b border-border px-4">
                <Search className="size-4 shrink-0 text-subtle" aria-hidden />
                <Command.Input
                  autoFocus
                  value={search}
                  onValueChange={setSearch}
                  placeholder="Search papers, authors, datasets… or jump to a page"
                  className="h-12 w-full bg-transparent text-body text-text outline-none placeholder:text-subtle"
                />
              </div>
              <Command.List className="max-h-[min(60vh,420px)] overflow-y-auto p-2">
                <Command.Empty className="px-3 py-8 text-center text-small text-muted">
                  No matching papers, pages or actions.
                </Command.Empty>
                {search.trim().length >= 2 && (
                  <Command.Group heading="Search" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-subtle">
                    <Command.Item
                      value={`search passages ${search}`}
                      onSelect={() =>
                        run(() => navigate(`/search?q=${encodeURIComponent(search.trim())}`))
                      }
                      className={itemClass}
                    >
                      <TextSearch className="size-4 shrink-0 text-muted" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">
                        Search passages for “{search.trim()}”
                      </span>
                    </Command.Item>
                  </Command.Group>
                )}
                {(papers.data?.items.length ?? 0) > 0 && (
                  <Command.Group heading="Papers" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-subtle">
                    {papers.data!.items.map((doc) => (
                      <Command.Item
                        key={doc.id}
                        value={`paper ${doc.id} ${doc.title} ${doc.authors_display} ${search}`}
                        onSelect={() => run(() => navigate(`/papers/${doc.id}`))}
                        className={itemClass}
                      >
                        <FileText className="size-4 shrink-0 text-muted" aria-hidden />
                        <span className="min-w-0 flex-1 truncate">{doc.title}</span>
                        <span className="hidden max-w-40 truncate text-caption text-subtle sm:block">
                          {doc.authors_display}
                        </span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                <Command.Group
                  heading="Go to"
                  className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-subtle"
                >
                  {allNav.map((item) => (
                    <Command.Item
                      key={item.to}
                      value={`${item.label} ${item.description}`}
                      onSelect={() => run(() => navigate(item.to))}
                      className={itemClass}
                    >
                      <item.icon className="size-4 text-muted" aria-hidden />
                      <span className="flex-1">{item.label}</span>
                      <span className="hidden truncate text-caption text-subtle sm:block">
                        {item.description}
                      </span>
                    </Command.Item>
                  ))}
                </Command.Group>
                <Command.Group
                  heading="Actions"
                  className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-subtle"
                >
                  <Command.Item
                    value="upload papers add files pdf"
                    onSelect={() => run(() => openUpload(true))}
                    className={itemClass}
                  >
                    <Upload className="size-4 text-muted" />
                    Upload papers
                  </Command.Item>
                  <Command.Item
                    value="new collection create project folder"
                    onSelect={() => run(() => setCreatingCollection(true))}
                    className={itemClass}
                  >
                    <FolderPlus className="size-4 text-muted" />
                    New collection
                  </Command.Item>
                  <Command.Item
                    value="toggle theme dark light mode"
                    onSelect={() =>
                      run(() => {
                        const next = isDark ? 'light' : 'dark'
                        setTheme(next)
                        sync({ theme: next })
                      })
                    }
                    className={itemClass}
                  >
                    {isDark ? <Sun className="size-4 text-muted" /> : <Moon className="size-4 text-muted" />}
                    Switch to {isDark ? 'light' : 'dark'} mode
                  </Command.Item>
                </Command.Group>
              </Command.List>
            </Command>
          </RadixDialog.Content>
        </RadixDialog.Portal>
      </RadixDialog.Root>
      {creatingCollection && (
        <CollectionDialog
          open={creatingCollection}
          onOpenChange={setCreatingCollection}
          onSaved={(collection) => navigate(`/collections/${collection.id}`)}
        />
      )}
    </>
  )
}
