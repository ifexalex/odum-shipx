/**
 * Whether the signed-in user's roles may open a page, for deciding between a link to the fix and "ask someone who
 * can" (FD-25). Null-safe outside a session provider: without a session, nothing opens.
 */
import { useContext } from 'react'
import { SessionContext } from '../auth/SessionContext'
import { canOpen } from './breadcrumbs'

export function useCanOpen(pathname: string): boolean {
  const session = useContext(SessionContext)?.session
  return !!session && canOpen(pathname, session.roles)
}
