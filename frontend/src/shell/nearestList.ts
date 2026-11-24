import type { UserRole } from '../auth/types'
import { routeTable } from './routeTable'

/**
 * The closest list above an unknown address that the user may open: `/billing/xyz/abc` → Billing. Walks the address
 * up one segment at a time and stops at the first route without parameters that one of the user's roles can open.
 * Null when there is none, or when it is the user's home page (already offered).
 */
export function nearestList(pathname: string, roles: readonly UserRole[], home: string): { to: string; label: string } | null {
  const segments = pathname.split('/').filter(Boolean)
  for (let n = segments.length; n > 0; n--) {
    const prefix = `/${segments.slice(0, n).join('/')}`
    const route = routeTable.find(
      (r) => r.path === prefix && r.layout !== 'none' && r.allow !== 'public' && roles.some((role) => r.allow.includes(role)),
    )
    if (route) return route.path === home ? null : { to: route.path, label: route.crumb ?? route.title }
  }
  return null
}
