import { useEffect, useLayoutEffect, useRef } from 'react'

export interface Hotkey {
  /** e.g. "mod+k", "/", "mod+u". `mod` = Ctrl on Windows/Linux, ⌘ on macOS. */
  combo: string
  handler: (event: KeyboardEvent) => void
  /** Fire even while typing in an input (default false, except for mod combos). */
  allowInInputs?: boolean
}

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
export const modKeyLabel = isMac ? '⌘' : 'Ctrl'

function isTypingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

function matches(event: KeyboardEvent, combo: string) {
  const parts = combo.toLowerCase().split('+')
  const key = parts.pop()
  const wantsMod = parts.includes('mod')
  const hasMod = isMac ? event.metaKey : event.ctrlKey
  return event.key.toLowerCase() === key && wantsMod === hasMod && !event.altKey
}

export function useHotkeys(hotkeys: Hotkey[]) {
  const ref = useRef(hotkeys)
  useLayoutEffect(() => {
    ref.current = hotkeys
  })

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      for (const hotkey of ref.current) {
        if (!matches(event, hotkey.combo)) continue
        const allow = hotkey.allowInInputs ?? hotkey.combo.includes('mod')
        if (!allow && isTypingTarget(event.target)) continue
        event.preventDefault()
        hotkey.handler(event)
        return
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])
}
