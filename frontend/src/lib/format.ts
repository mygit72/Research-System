/** Two-letter avatar initials from a display name, falling back to the email. */
export function initials(name: string, email: string) {
  const source = name.trim() || email
  const parts = source.split(/[\s@._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || '?'
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['second', 60],
  ['minute', 60],
  ['hour', 24],
  ['day', 7],
  ['week', 4.35],
  ['month', 12],
  ['year', Number.POSITIVE_INFINITY],
]

export function timeAgo(iso: string, now: number = Date.now()) {
  let value = (new Date(iso).getTime() - now) / 1000
  for (const [unit, size] of STEPS) {
    if (Math.abs(value) < size) return relative.format(Math.round(value), unit)
    value /= size
  }
  return new Date(iso).toLocaleDateString()
}

/** Remaining seconds from progress so far, or null when there isn't enough signal yet. */
export function estimateRemaining(startedAt: string | null, progress: number, now = Date.now()) {
  if (!startedAt || progress < 0.05 || progress >= 1) return null
  const elapsed = (now - new Date(startedAt).getTime()) / 1000
  if (elapsed < 2) return null
  return Math.max(1, Math.round((elapsed / progress) * (1 - progress)))
}

export function formatDuration(seconds: number) {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.round(seconds / 60)
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}
