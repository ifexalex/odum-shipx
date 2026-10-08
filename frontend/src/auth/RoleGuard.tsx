import type { JSX, ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { homePathForRole } from './roleHome'
import { SessionLoading } from './SessionLoading'
import { useSession } from './SessionContext'
import type { UserRole } from './types'

export interface RoleGuardProps {
  allow: UserRole[]
  children: ReactNode
  /** Where to send an unauthenticated visitor. Defaults to "/login". */
  unauthenticatedRedirectTo?: string
}

// This is a UX convenience, not a security boundary (CLAUDE.md principle —
// tenant isolation and role enforcement are backend properties). A role
// hitting a route it shouldn't see gets redirected client-side; the *real*
// protection is that the API returns 403 regardless. Treat any mismatch here
// as a frontend nav bug to fix, not a permission system to harden.
//
// Two distinct redirect targets (06_routing_rbac_and_navigation.md AC):
// no session at all -> /login; authenticated but wrong role -> that role's
// own home page (never a blank screen, never the wrong tenant's nav).
export function RoleGuard({ allow, children, unauthenticatedRedirectTo = '/login' }: RoleGuardProps): JSX.Element {
  const { session, status } = useSession()

  // SessionProvider's mount-time silent-restore (httpOnly refresh-token
  // cookie → fresh ID token) is still in flight — wait for it rather than
  // bouncing to /login, or a page reload would always show the login screen
  // for a moment even when the session is about to come back.
  if (status === 'loading') {
    return <SessionLoading />
  }

  if (status !== 'authenticated' || !session) {
    return <Navigate to={unauthenticatedRedirectTo} replace />
  }

  // Authorization is governed by the user's full role set, not just the
  // currently active/display role — a route allowed for either of a
  // multi-role user's roles must not bounce them just because the *other*
  // role is active for nav/display purposes.
  if (!allow.some((role) => session.roles.includes(role))) {
    return <Navigate to={homePathForRole(session.role)} replace />
  }

  return <>{children}</>
}
