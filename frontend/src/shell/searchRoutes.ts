import type { SearchResult, SearchResultKind } from '../api/search'
import type { UserRole } from '../auth/types'

export type SearchAudience = 'staff' | 'customer'

export const SEARCH_KIND_LABELS: Record<SearchResultKind, string> = {
  container: 'Container',
  shipment: 'Shipment',
  invoice: 'Invoice',
  release_note: 'Release note',
  customer: 'Customer',
}

// Where each kind of result opens. A customer reaches the same records through their own portal routes, never the
// staff ones (routeTable.ts keeps `customer` out of every staff route's `allow` list). `shipment` is the packing
// list in both worlds, and both routes take the packing-list id.
const STAFF_PATHS: Record<SearchResultKind, (id: string) => string> = {
  container: (id) => `/containers/${id}`,
  shipment: (id) => `/packing-lists/${id}`,
  invoice: (id) => `/billing/${id}`,
  release_note: (id) => `/release-notes/${id}`,
  customer: (id) => `/admin/customers/${id}`,
}

const CUSTOMER_PATHS: Partial<Record<SearchResultKind, (id: string) => string>> = {
  shipment: (id) => `/my-shipments/${id}`,
  invoice: (id) => `/my-billing/${id}`,
  release_note: (id) => `/my-release-notes/${id}`,
}

/** The route a result opens, or null if this audience has no page for that kind (the server never sends one). */
export function searchResultPath(result: Pick<SearchResult, 'kind' | 'id'>, audience: SearchAudience): string | null {
  const build = audience === 'customer' ? CUSTOMER_PATHS[result.kind] : STAFF_PATHS[result.kind]
  return build ? build(encodeURIComponent(result.id)) : null
}

// What the box says it searches. Copy only: the server decides what a role may actually find
// (services/search/service.py `_KINDS`), so a stale entry here misleads but never over-exposes.
const PLACEHOLDERS: Partial<Record<UserRole, string>> = {
  tenant_admin: 'Search containers, invoices, customers…',
  nigeria_office_staff: 'Search containers, invoices, customers…',
  china_office_staff: 'Search containers, shipments…',
  warehouse_attendant: 'Search release notes…',
  customer: 'Search shipments, invoices…',
}

/** The search box's placeholder for a role, or null if that role has no global search (platform admins span tenants). */
export function searchPlaceholderFor(role: UserRole): string | null {
  return PLACEHOLDERS[role] ?? null
}
