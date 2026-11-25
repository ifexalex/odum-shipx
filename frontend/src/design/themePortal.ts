import { createContext, useContext } from 'react'

/** Active `[data-tenant-theme]` element so portals (modals) inherit tenant CSS tokens. */
export const ThemePortalContext = createContext<HTMLElement | null>(null)

export function useThemePortalTarget(): HTMLElement | null {
  return useContext(ThemePortalContext)
}
