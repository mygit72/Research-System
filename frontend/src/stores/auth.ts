/**
 * Auth state. The access token lives only in memory; the refresh token is an
 * httpOnly cookie the browser manages. On page load `bootstrap()` silently
 * exchanges the cookie for an access token.
 */
import { create } from 'zustand'
import { accountApi, authApi } from '@/services/api'
import { configureAuth, refreshSession } from '@/services/http'
import type { TokenResponse, User } from '@/types/api'

type Status = 'loading' | 'authenticated' | 'anonymous'

interface AuthState {
  status: Status
  user: User | null
  accessToken: string | null
  bootstrap: () => Promise<void>
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, fullName: string) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: User) => void
  setTokens: (tokens: TokenResponse) => void
}

export const useAuth = create<AuthState>((set) => ({
  status: 'loading',
  user: null,
  accessToken: null,

  bootstrap: async () => {
    const tokens = await refreshSession()
    if (!tokens) {
      set({ status: 'anonymous', user: null, accessToken: null })
      return
    }
    try {
      const user = await accountApi.me()
      set({ status: 'authenticated', user })
    } catch {
      set({ status: 'anonymous', user: null, accessToken: null })
    }
  },

  login: async (email, password) => {
    const tokens = await authApi.login({ email, password })
    set({ accessToken: tokens.access_token })
    const user = await accountApi.me()
    set({ status: 'authenticated', user })
  },

  register: async (email, password, fullName) => {
    const response = await authApi.register({ email, password, full_name: fullName })
    set({ status: 'authenticated', accessToken: response.access_token, user: response.user })
  },

  logout: async () => {
    try {
      await authApi.logout()
    } finally {
      set({ status: 'anonymous', user: null, accessToken: null })
    }
  },

  setUser: (user) => set({ user }),
  setTokens: (tokens) => set({ accessToken: tokens.access_token }),
}))

configureAuth({
  getAccessToken: () => useAuth.getState().accessToken,
  onTokens: (tokens) => useAuth.getState().setTokens(tokens),
  onSessionExpired: () => {
    if (useAuth.getState().status === 'authenticated') {
      useAuth.setState({ status: 'anonymous', user: null, accessToken: null })
    }
  },
})
