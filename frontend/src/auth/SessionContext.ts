import { createContext, useContext } from 'react'
import type { Session, UserRole } from './types'

export type SessionStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface SessionContextValue {
  session: Session | null
  status: SessionStatus
  /** Resolves with the new Session so callers can redirect by role without racing a re-render. */
  login: (email: string, password: string) => Promise<Session>
  logout: () => void
  /** Swaps the active session to an impersonation token returned by POST /v1/platform/tenants/{id}/impersonate. */
  startImpersonation: (idToken: string, tenantName?: string) => void
  /** Restores the platform admin's own session. Safe to call even if not impersonating. */
  exitImpersonation: () => void
  /** Forces an immediate silent refresh — used by the Task 05 API client on a 401. */
  refreshNow: () => Promise<void>
  /**
   * Switches the active/display role for a multi-role user — client-side
   * only, no network call, no new token. `role` must be a member of
   * `session.roles`; a no-op otherwise. Authorization is unaffected either
   * way — it's always governed by the full `session.roles` set server-side.
   */
  setActiveRole: (role: UserRole) => void
}

export const SessionContext = createContext<SessionContextValue | null>(null)

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used within a SessionProvider')
  return ctx
}
