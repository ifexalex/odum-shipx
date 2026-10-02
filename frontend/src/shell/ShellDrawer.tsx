import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

// Mobile-drawer plumbing shared by both PageShell (staff/admin/platform/
// china shells) and CustShell (customer shell) — extracted out of
// PageShell.tsx so the customer shell doesn't have to duplicate the
// open/toggle/close + Escape-to-close logic. A hamburger button (TopBar's
// or CustomerTopNav's) toggles it through this context; each shell owns
// its own provider instance and renders its own drawer overlay/panel
// markup, since the two shells' drawer *contents* differ (Sidebar vs. a
// vertical nav list) even though the state machine is identical.
export interface ShellDrawerValue {
  open: boolean
  toggle: () => void
  close: () => void
}

const ShellDrawerContext = createContext<ShellDrawerValue | null>(null)

// Null outside a provider so TopBar/CustomerTopNav can render standalone in tests.
export function useShellDrawer(): ShellDrawerValue | null {
  return useContext(ShellDrawerContext)
}

export const ShellDrawerProvider = ShellDrawerContext.Provider

/** Open/toggle/close state + Escape-to-close — one instance per shell. */
export function useDrawerState(): ShellDrawerValue {
  const [open, setOpen] = useState(false)
  const toggle = useCallback(() => setOpen((v) => !v), [])
  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return useMemo(() => ({ open, toggle, close }), [open, toggle, close])
}
