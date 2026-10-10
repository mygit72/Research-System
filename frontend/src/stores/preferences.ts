/**
 * UI preferences (theme, font size, sidebar). Persisted to localStorage so the
 * first paint is correct, and mirrored to the user's server-side preferences
 * so they follow the account across devices.
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { FontScale, Theme, UserPreferences } from '@/types/api'

interface PreferencesState {
  theme: Theme
  fontScale: FontScale
  sidebarCollapsed: boolean
  showAdvanced: boolean
  setShowAdvanced: (show: boolean) => void
  setTheme: (theme: Theme) => void
  setFontScale: (scale: FontScale) => void
  setSidebarCollapsed: (collapsed: boolean) => void
  hydrateFromServer: (prefs: UserPreferences) => void
}

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      theme: 'system',
      fontScale: 'md',
      sidebarCollapsed: false,
      showAdvanced: false,
      setShowAdvanced: (showAdvanced) => set({ showAdvanced }),
      setTheme: (theme) => set({ theme }),
      setFontScale: (fontScale) => set({ fontScale }),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      hydrateFromServer: (prefs) =>
        set((state) => ({
          theme: prefs.theme ?? state.theme,
          fontScale: prefs.font_scale ?? state.fontScale,
          sidebarCollapsed: prefs.sidebar_collapsed ?? state.sidebarCollapsed,
          showAdvanced: prefs.show_advanced ?? state.showAdvanced,
        })),
    }),
    { name: 'ri-preferences' },
  ),
)

export function resolveTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Applies theme + font scale to <html>. Call once at startup; it keeps itself in sync. */
export function applyPreferencesToDocument() {
  const apply = () => {
    const { theme, fontScale } = usePreferences.getState()
    const root = document.documentElement
    root.dataset.theme = resolveTheme(theme)
    root.dataset.fontScale = fontScale
  }
  apply()
  usePreferences.subscribe(apply)
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', apply)
}
