import { Toaster } from 'sonner'
import { resolveTheme, usePreferences } from '@/stores/preferences'

export function ThemedToaster() {
  const theme = usePreferences((s) => s.theme)
  return <Toaster position="bottom-right" theme={resolveTheme(theme)} closeButton />
}
