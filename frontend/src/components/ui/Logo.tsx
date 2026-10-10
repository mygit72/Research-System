import { cn } from '@/lib/cn'

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn('size-7 shrink-0', className)} aria-hidden>
      <rect width="32" height="32" rx="7" className="fill-primary" />
      <path
        d="M9 8h9.5a5.5 5.5 0 0 1 1.6 10.76L24 24h-3.6l-3.4-4.8H12.2V24H9V8Zm3.2 3v5.2h6.1a2.6 2.6 0 0 0 0-5.2h-6.1Z"
        className="fill-primary-fg"
      />
    </svg>
  )
}

export function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && (
        <span className="text-[0.9375rem] leading-tight font-semibold tracking-tight text-text">
          Research Intelligence
        </span>
      )}
    </span>
  )
}
