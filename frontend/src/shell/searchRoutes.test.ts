import { matchPath } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { SearchResultKind } from '../api/search'
import type { UserRole } from '../auth/types'
import { routeTable } from './routeTable'
import { searchPlaceholderFor, searchResultPath } from './searchRoutes'

// What each role may find: a copy of services/search/service.py `_KINDS`. If the server's map changes, this must too,
// and the test below then proves every kind still opens a page that role is allowed into.
const KINDS_BY_ROLE: Record<Exclude<UserRole, 'platform_admin'>, SearchResultKind[]> = {
  tenant_admin: ['container', 'shipment', 'invoice', 'release_note', 'customer'],
  nigeria_office_staff: ['container', 'shipment', 'invoice', 'release_note'],
  china_office_staff: ['container', 'shipment'],
  warehouse_attendant: ['release_note'],
  customer: ['shipment', 'invoice', 'release_note'],
}

function routeFor(path: string) {
  return routeTable.find((route) => matchPath({ path: route.path, end: true }, path) !== null && route.allow !== 'public')
}

describe('searchResultPath', () => {
  it.each(Object.entries(KINDS_BY_ROLE))('every kind %s can find opens a page that role may enter', (role, kinds) => {
    const audience = role === 'customer' ? 'customer' : 'staff'
    for (const kind of kinds) {
      const path = searchResultPath({ kind, id: 'abc-123' }, audience)
      expect(path, `${role} / ${kind}`).not.toBeNull()
      const route = routeFor(path as string)
      expect(route, `${role} / ${kind} -> ${path}`).toBeDefined()
      expect(route!.allow, `${path} must admit ${role}`).toContain(role)
    }
  })

  it('sends a customer to their own portal routes, never a staff one', () => {
    expect(searchResultPath({ kind: 'shipment', id: 'p1' }, 'customer')).toBe('/my-shipments/p1')
    expect(searchResultPath({ kind: 'invoice', id: 'b1' }, 'customer')).toBe('/my-billing/b1')
    expect(searchResultPath({ kind: 'release_note', id: 'r1' }, 'customer')).toBe('/my-release-notes/r1')
  })

  it('has no customer page for kinds a customer is never sent', () => {
    expect(searchResultPath({ kind: 'container', id: 'c1' }, 'customer')).toBeNull()
    expect(searchResultPath({ kind: 'customer', id: 'u1' }, 'customer')).toBeNull()
  })

  it('encodes the id so it cannot rewrite the path', () => {
    expect(searchResultPath({ kind: 'container', id: '../admin/users' }, 'staff')).toBe('/containers/..%2Fadmin%2Fusers')
  })
})

describe('searchPlaceholderFor', () => {
  it('has copy for every role that can search', () => {
    for (const role of Object.keys(KINDS_BY_ROLE) as UserRole[]) {
      expect(searchPlaceholderFor(role), role).toEqual(expect.any(String))
    }
  })

  it('has none for a platform admin', () => {
    expect(searchPlaceholderFor('platform_admin')).toBeNull()
  })
})
