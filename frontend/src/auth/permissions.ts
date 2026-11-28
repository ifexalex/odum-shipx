import type { Session, UserRole } from './types'

/**
 * True if ``roles`` includes at least one of ``allowed``.
 * Use this instead of ``session.role === ...`` so multi-role users see every
 * action their assigned roles authorize (matching backend ``ctx.has_role``).
 */
export function hasRole(roles: readonly UserRole[] | null | undefined, ...allowed: UserRole[]): boolean {
  if (!roles || roles.length === 0) return false
  return allowed.some((role) => roles.includes(role))
}

/** Convenience wrapper accepting a ``Session`` (null-safe). */
export function sessionHasRole(session: Session | null | undefined, ...allowed: UserRole[]): boolean {
  return hasRole(session?.roles, ...allowed)
}
