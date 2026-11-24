import { describe, expect, it } from 'vitest'
import type { UserRole } from '../auth/types'
import { activeNavPath, navConfig, roleForPath, visualRoleFor } from './navConfig'
import { routeTable } from './routeTable'

const ALL_ROLES: UserRole[] = [
  'platform_admin',
  'tenant_admin',
  'china_office_staff',
  'nigeria_office_staff',
  'warehouse_attendant',
  'customer',
]

describe('navConfig', () => {
  it('every nav path is guarded for that role in routeTable (no drift between nav and guards)', () => {
    for (const role of ALL_ROLES) {
      for (const group of navConfig[role]) {
        for (const item of group.items) {
          // Static paths only — dynamic params like /containers/:id never appear as nav items.
          const route = routeTable.find((r) => r.path === item.path)
          expect(route, `nav path ${item.path} (role ${role}) is missing from routeTable`).toBeDefined()
          expect(route!.allow).not.toBe('public')
          expect(route!.allow).toContain(role)
        }
      }
    }
  })

  it('maps every backend role to a distinct visual role', () => {
    const mapped = ALL_ROLES.map(visualRoleFor)
    expect(new Set(mapped).size).toBe(ALL_ROLES.length)
  })

  it('china_office_staff and nigeria_office_staff get distinct nav', () => {
    expect(navConfig.china_office_staff).not.toEqual(navConfig.nigeria_office_staff)
  })
})

describe('roleForPath', () => {
  it('finds the assigned role whose nav owns a path the preferred role does not', () => {
    expect(roleForPath('/warehouse', ['nigeria_office_staff', 'warehouse_attendant'], 'nigeria_office_staff'))
      .toBe('warehouse_attendant')
  })

  it('matches nested detail paths, not just exact nav-item paths', () => {
    expect(roleForPath('/warehouse/abc123', ['nigeria_office_staff', 'warehouse_attendant'], 'nigeria_office_staff'))
      .toBe('warehouse_attendant')
  })

  it('keeps the preferred role when its own nav already owns the path (no false-positive flip)', () => {
    expect(roleForPath('/dashboard', ['nigeria_office_staff', 'warehouse_attendant'], 'nigeria_office_staff'))
      .toBe('nigeria_office_staff')
  })

  it('returns null when no assigned role\'s nav owns the path (e.g. a shared account/profile route)', () => {
    expect(roleForPath('/profile', ['nigeria_office_staff', 'warehouse_attendant'], 'nigeria_office_staff'))
      .toBeNull()
  })

  it('returns null for a single-role user (nothing to correct to)', () => {
    expect(roleForPath('/my-shipments', ['customer'], 'customer')).toBe('customer')
    expect(roleForPath('/warehouse', ['customer'], 'customer')).toBeNull()
  })
})

describe('Nigeria office menu', () => {
  const labels = navConfig.nigeria_office_staff.flatMap((g) => g.items.map((i) => i.label))

  it('offers Containers, Packing lists and Manifests', () => {
    expect(labels).toEqual(expect.arrayContaining(['Containers', 'Packing lists', 'Manifests']))
  })

  it('lists each entry once', () => {
    expect(new Set(labels).size).toBe(labels.length)
  })

  it('only links to pages the route table lets Nigeria staff open', () => {
    for (const group of navConfig.nigeria_office_staff) {
      for (const item of group.items) {
        expect(roleForPath(item.path, ['nigeria_office_staff'], 'nigeria_office_staff')).toBe('nigeria_office_staff')
      }
    }
  })
})

describe('China office menu (UX-08)', () => {
  it('lists Missing items under Coordination, beside CBM disputes (Manifests is under Operations)', () => {
    const coordination = navConfig.china_office_staff.find((group) => group.group === 'Coordination')
    expect(coordination?.items.map((item) => item.label)).toEqual(['CBM disputes', 'Missing items'])
    expect(coordination?.items.at(-1)?.path).toBe('/claims/missing-items')
  })
})

describe('the menu (FD-15)', () => {
  const sample = (path: string): string => path.replace(/:\w+/g, 'x1')
  const itemPaths = (role: UserRole): string[] => navConfig[role].flatMap((g) => g.items.map((i) => i.path))

  it.each(ALL_ROLES)('lights at most one item on every route %s can open', (role) => {
    for (const route of routeTable.filter((r) => r.allow !== 'public' && r.allow.includes(role))) {
      const path = sample(route.path)
      const lit = itemPaths(role).filter((p) => p === activeNavPath(path, itemPaths(role)))
      expect(lit.length, path).toBeLessThanOrEqual(1)
    }
  })

  it('lights the deepest item: a sub-page is not also its parent section', () => {
    const admin = itemPaths('tenant_admin')
    expect(activeNavPath('/claims/missing-items', admin)).toBe('/claims/missing-items')
    expect(activeNavPath('/claims/c1', admin)).toBe('/claims')
    expect(activeNavPath('/packing-lists/new', admin)).toBe('/packing-lists')
    expect(activeNavPath('/billing/disputes/d1', itemPaths('china_office_staff'))).toBe('/billing/disputes')
    expect(activeNavPath('/profile', admin)).toBeNull()
  })

  it.each(ALL_ROLES)('gives every item of %s its own icon', (role) => {
    const icons = navConfig[role].flatMap((g) => g.items.map((i) => i.icon))
    expect(icons.every(Boolean)).toBe(true)
    expect(new Set(icons).size).toBe(icons.length)
  })

  it.each(ALL_ROLES)('uses sentence case for %s, and offers no "Create" page as a menu item', (role) => {
    for (const group of navConfig[role]) {
      for (const label of [group.group, ...group.items.map((i) => i.label)].filter(Boolean) as string[]) {
        expect(label, label).not.toMatch(/^\S+ [A-Z][a-z]/) // "Packing Lists"
        expect(label).not.toMatch(/^Create\b/)
      }
      for (const item of group.items) expect(item.path).not.toMatch(/\/(new|import)$/)
    }
  })

  it('groups the tenant admin’s menu as Overview, Operations, Billing and claims, Admin', () => {
    expect(navConfig.tenant_admin.map((g) => g.group)).toEqual(['Overview', 'Operations', 'Billing and claims', 'Admin'])
  })
})
