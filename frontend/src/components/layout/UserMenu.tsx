import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { HelpCircle, LogOut, Monitor, Moon, Settings, Sun } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { usePreferenceSync } from '@/hooks/usePreferenceSync'
import { cn } from '@/lib/cn'
import { initials } from '@/lib/format'
import { useAuth } from '@/stores/auth'
import { usePreferences } from '@/stores/preferences'
import type { Theme } from '@/types/api'

const itemClass =
  'flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-small text-text outline-none select-none data-[highlighted]:bg-surface-muted'


const themes: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

export function UserMenu() {
  const user = useAuth((s) => s.user)
  const logout = useAuth((s) => s.logout)
  const theme = usePreferences((s) => s.theme)
  const setTheme = usePreferences((s) => s.setTheme)
  const sync = usePreferenceSync()
  const navigate = useNavigate()
  if (!user) return null

  return (
    <Dropdown.Root>
      <Dropdown.Trigger
        aria-label="Account menu"
        className="flex size-8 items-center justify-center rounded-full bg-primary-soft text-caption font-semibold text-primary hover:ring-2 hover:ring-border"
      >
        {initials(user.full_name, user.email)}
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content
          align="end"
          sideOffset={8}
          className="z-50 w-60 rounded-lg border border-border bg-surface-elevated p-1 shadow-lg animate-fade-in"
        >
          <div className="px-2 py-2">
            <p className="truncate text-small font-medium text-text">{user.full_name || 'Researcher'}</p>
            <p className="truncate text-caption text-muted">{user.email}</p>
          </div>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <Dropdown.Label className="px-2 pt-1 pb-1 text-caption text-subtle">Theme</Dropdown.Label>
          <div className="flex gap-1 px-1 pb-1" role="radiogroup" aria-label="Theme">
            {themes.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                role="radio"
                aria-checked={theme === value}
                onClick={() => {
                  setTheme(value)
                  sync({ theme: value })
                }}
                className={cn(
                  'flex flex-1 items-center justify-center gap-1.5 rounded-sm py-1.5 text-caption',
                  theme === value
                    ? 'bg-primary-soft font-medium text-primary'
                    : 'text-muted hover:bg-surface-muted',
                )}
              >
                <Icon className="size-3.5" aria-hidden /> {label}
              </button>
            ))}
          </div>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <Dropdown.Item className={itemClass} onSelect={() => navigate('/settings')}>
            <Settings className="size-4 text-muted" /> Settings
          </Dropdown.Item>
          <Dropdown.Item className={itemClass} onSelect={() => navigate('/help')}>
            <HelpCircle className="size-4 text-muted" /> Help & shortcuts
          </Dropdown.Item>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <Dropdown.Item
            className={itemClass}
            onSelect={async () => {
              await logout()
              navigate('/login')
            }}
          >
            <LogOut className="size-4 text-muted" /> Sign out
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  )
}
