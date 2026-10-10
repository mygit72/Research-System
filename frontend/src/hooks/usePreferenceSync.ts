import { useCallback } from 'react'
import { accountApi } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { UserPreferences } from '@/types/api'

/** Persist a preference change to the account (fire-and-forget; local state already updated). */
export function usePreferenceSync() {
  const setUser = useAuth((s) => s.setUser)
  const authenticated = useAuth((s) => s.status === 'authenticated')
  return useCallback(
    (preferences: UserPreferences) => {
      if (!authenticated) return
      accountApi
        .update({ preferences })
        .then(setUser)
        .catch(() => {
          /* non-critical: the local preference still applies */
        })
    },
    [authenticated, setUser],
  )
}
