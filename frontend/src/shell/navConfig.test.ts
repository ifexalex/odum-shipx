import { describe, expect, it } from 'vitest'
import type { UserRole } from '../auth/types'
import { navConfig, roleForPath, visualRoleFor } from './navConfig'
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

  it('offers Containers, Packing Lists and Manifests', () => {
    expect(labels).toEqual(expect.arrayContaining(['Containers', 'Packing Lists', 'Manifests']))
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
  it('lists Missing items under Coordination, beside Manifests and CBM disputes', () => {
    const coordination = navConfig.china_office_staff.find((group) => group.group === 'Coordination')
    expect(coordination?.items.map((item) => item.label)).toEqual(['Manifests', 'CBM disputes', 'Missing items'])
    expect(coordination?.items.at(-1)?.path).toBe('/claims/missing-items')
  })
})
