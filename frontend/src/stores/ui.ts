import { create } from 'zustand'

/** Transient UI state (not persisted). */
interface UIState {
  commandOpen: boolean
  mobileNavOpen: boolean
  setCommandOpen: (open: boolean) => void
  setMobileNavOpen: (open: boolean) => void
}

export const useUI = create<UIState>((set) => ({
  commandOpen: false,
  mobileNavOpen: false,
  setCommandOpen: (commandOpen) => set({ commandOpen }),
  setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
}))
