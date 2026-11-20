/**
 * Browser tab titles (audit FD-48).
 *
 * A tab names the page, then where it lives, then whose account it is: "INV-A-002 · Billing · Acme Shipping". It is
 * the breadcrumb trail read from the current page upwards (so a record page shows its reference once loaded, and its
 * route's name until then), or, on a top-level page, the route's title. Staff tabs end with the tenant's display name;
 * customer and public tabs end with "ShipX".
 */
import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import type { UserRole } from '../auth/types'
import { breadcrumbTrail, matchRoute } from './breadcrumbs'

export const APP_NAME = 'ShipX'

/**
 * The tab title for `pathname`.
 *
 * @param pathname The current location.
 * @param roles Every role the user holds (decides which ancestors the trail shows); empty for a public page.
 * @param labels Record labels the pages supplied, by route pattern.
 * @param owner Whose account this is (the tenant's display name); defaults to the app's name.
 */
export function documentTitle(
  pathname: string,
  roles: readonly UserRole[],
  labels: Readonly<Record<string, string>> = {},
  owner?: string | null,
): string {
  const trail = breadcrumbTrail(pathname, roles, labels)
  const page = trail.length > 0 ? trail.map((crumb) => crumb.label).reverse() : [matchRoute(pathname)?.route.title]
  return [...page, owner?.trim() || APP_NAME].filter(Boolean).join(' · ')
}

/** Keep `document.title` in step with the page (see `documentTitle`). */
export function useDocumentTitle(
  roles: readonly UserRole[],
  labels: Readonly<Record<string, string>> = {},
  owner?: string | null,
): void {
  const { pathname } = useLocation()
  const title = documentTitle(pathname, roles, labels, owner)
  useEffect(() => {
    document.title = title
  }, [title])
}
