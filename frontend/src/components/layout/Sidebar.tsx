import { NavLink } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { Logo } from '@/components/ui/Logo'
import { Tooltip } from '@/components/ui/Tooltip'
import { usePreferenceSync } from '@/hooks/usePreferenceSync'
import { cn } from '@/lib/cn'
import { primaryNav, secondaryNav, type NavItem } from '@/lib/navigation'
import { usePreferences } from '@/stores/preferences'

function NavEntry({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem
  collapsed: boolean
  onNavigate?: () => void
}) {
  const Icon = item.icon
  return (
    <Tooltip content={item.label} side="right" disabled={!collapsed}>
      <NavLink
        to={item.to}
        end={item.to === '/'}
        onClick={onNavigate}
        aria-label={collapsed ? item.label : undefined}
        className={({ isActive }) =>
          cn(
            'group flex h-9 items-center gap-3 rounded-md px-2.5 text-small font-medium transition-colors',
            collapsed && 'justify-center px-0',
            isActive
              ? 'bg-surface-muted text-text'
              : 'text-muted hover:bg-surface-muted/70 hover:text-text',
          )
        }
      >
        {({ isActive }) => (
          <>
            <Icon
              className={cn('size-[18px] shrink-0', isActive ? 'text-primary' : 'text-subtle')}
              aria-hidden
            />
            {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
          </>
        )}
      </NavLink>
    </Tooltip>
  )
}

export function SidebarContent({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean
  onNavigate?: () => void
}) {
  return (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 px-2">
      {primaryNav.map((item) => (
        <NavEntry key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
      ))}
      <div className="my-3 border-t border-border" role="separator" />
      {secondaryNav.map((item) => (
        <NavEntry key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
      ))}
    </nav>
  )
}

/** Persistent desktop sidebar (lg+). Collapses to icons with tooltips. */
export function Sidebar() {
  const collapsed = usePreferences((s) => s.sidebarCollapsed)
  const setCollapsed = usePreferences((s) => s.setSidebarCollapsed)
  const sync = usePreferenceSync()

  const toggle = () => {
    setCollapsed(!collapsed)
    sync({ sidebar_collapsed: !collapsed })
  }

  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-surface lg:flex',
        'transition-[width] duration-200',
        collapsed ? 'w-[60px]' : 'w-60',
      )}
    >
      <div className={cn('flex h-14 items-center px-4', collapsed && 'justify-center px-0')}>
        <Logo collapsed={collapsed} />
      </div>
      <div className="flex flex-1 flex-col overflow-y-auto py-2">
        <SidebarContent collapsed={collapsed} />
      </div>
      <div className={cn('border-t border-border p-2', collapsed && 'flex justify-center')}>
        <Tooltip content={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} side="right">
          <button
            onClick={toggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            className="flex h-8 items-center gap-2 rounded-md px-2 text-small text-muted hover:bg-surface-muted hover:text-text"
          >
            {collapsed ? (
              <PanelLeftOpen className="size-4" />
            ) : (
              <>
                <PanelLeftClose className="size-4" /> Collapse
              </>
            )}
          </button>
        </Tooltip>
      </div>
    </aside>
  )
}
