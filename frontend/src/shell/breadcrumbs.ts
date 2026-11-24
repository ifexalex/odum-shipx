/**
 * Breadcrumb trails (audit FD-45/FD-46).
 *
 * A page's trail is where it lives, not how the user got there: its chain of `parent` routes in `routeTable.ts`, each
 * a link, then the page itself. Top-level pages have no parent and no breadcrumb. A record page (an invoice, a packing
 * list) names itself once its record has loaded, through `useBreadcrumbLabel`; until then the route's `crumb` stands
 * in ("Invoice"). The trail never uses sidebar group names, and is the same for every role, except that a parent the
 * role cannot open is left out rather than shown as a link that bounces them to their home page.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { generatePath, matchRoutes, useLocation } from 'react-router-dom'
import type { UserRole } from '../auth/types'
import { routeTable, type RouteDef } from './routeTable'

export interface Crumb {
  label: string
  /** Where the crumb links to; absent for the current page. */
  to?: string
}

/** Record labels supplied by the pages on screen, keyed by route path pattern (`/billing/:id`). */
export interface BreadcrumbLabels {
  labels: Readonly<Record<string, string>>
  setLabel: (routePath: string, label: string | null) => void
}

export const BreadcrumbContext = createContext<BreadcrumbLabels>({ labels: {}, setLabel: () => {} })

const byPath = new Map(routeTable.map((route) => [route.path, route]))

/** The route `pathname` renders, ranked the way React Router ranks it (`/billing/disputes` before `/billing/:id`). */
export function matchRoute(pathname: string): { route: RouteDef; params: Record<string, string | undefined> } | null {
  const matches = matchRoutes(
    routeTable.map((route) => ({ path: route.path })),
    pathname,
  )
  const match = matches?.[matches.length - 1]
  if (!match?.route.path) return null
  const route = byPath.get(match.route.path)
  return route ? { route, params: match.params } : null
}

function allows(route: RouteDef, roles: readonly UserRole[]): boolean {
  return route.allow === 'public' || roles.some((role) => (route.allow as UserRole[]).includes(role))
}

/** Whether one of `roles` may open `pathname` (a concrete address such as `/admin/customers/c1`). */
export function canOpen(pathname: string, roles: readonly UserRole[]): boolean {
  const match = matchRoute(pathname)
  return !!match && allows(match.route, roles)
}

/**
 * The trail for `pathname`: every ancestor as a link, then the current page. Empty for a top-level page.
 *
 * @param pathname The current location.
 * @param roles Every role the user holds; an ancestor none of them may open is left out.
 * @param labels Record labels the pages supplied, by route pattern.
 */
export function breadcrumbTrail(
  pathname: string,
  roles: readonly UserRole[],
  labels: Readonly<Record<string, string>> = {},
): Crumb[] {
  const match = matchRoute(pathname)
  if (!match?.route.parent) return []
  const { route, params } = match
  const nameOf = (r: RouteDef): string => labels[r.path] ?? r.crumb ?? r.title

  const ancestors: Crumb[] = []
  for (let parent = byPath.get(route.parent!); parent; parent = parent.parent ? byPath.get(parent.parent) : undefined) {
    if (allows(parent, roles)) ancestors.unshift({ label: nameOf(parent), to: generatePath(parent.path, params) })
  }
  // Nothing above it this role can open (China staff on CBM disputes): a lone crumb would only repeat the title.
  if (ancestors.length === 0) return []
  const current = labels[route.path] ?? route.crumb ?? route.title
  return [...ancestors, { label: current }]
}

/**
 * Name a record page in the breadcrumb once its record has loaded: `useBreadcrumbLabel(invoice?.invoice_number)`.
 * A child page that knows its parent's record can name it too, by passing the parent's route pattern:
 * `useBreadcrumbLabel(draft?.reference, '/packing-lists/:id')` on the edit page. Cleared when the page unmounts.
 */
export function useBreadcrumbLabel(label: string | null | undefined, routePath?: string): void {
  const { setLabel } = useContext(BreadcrumbContext)
  const { pathname } = useLocation()
  const target = routePath ?? matchRoute(pathname)?.route.path
  useEffect(() => {
    if (!target) return undefined
    setLabel(target, label || null)
    return () => setLabel(target, null)
  }, [target, label, setLabel])
}

/** The value a layout provides on `BreadcrumbContext`: record labels the pages on screen have supplied. */
export function useBreadcrumbLabelState(): BreadcrumbLabels {
  const [labels, setLabels] = useState<Record<string, string>>({})
  const setLabel = useCallback((routePath: string, label: string | null) => {
    setLabels((current) => {
      if ((current[routePath] ?? null) === label) return current
      const next = { ...current }
      if (label === null) delete next[routePath]
      else next[routePath] = label
      return next
    })
  }, [])
  return useMemo(() => ({ labels, setLabel }), [labels, setLabel])
}
