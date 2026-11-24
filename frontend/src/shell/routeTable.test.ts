import { describe, expect, it } from 'vitest'
import { routeTable } from './routeTable'

describe('routeTable', () => {
  it('has no duplicate paths', () => {
    const paths = routeTable.map((r) => r.path)
    expect(new Set(paths).size).toBe(paths.length)
  })

  it('never sends a customer into the staff layout', () => {
    for (const route of routeTable) {
      if (route.layout === 'staff' && route.allow !== 'public') {
        expect(route.allow).not.toContain('customer')
      }
    }
  })

  it('only allows customer on customer-layout routes', () => {
    for (const route of routeTable) {
      if (route.allow !== 'public' && route.allow.includes('customer')) {
        expect(route.layout).toBe('customer')
      }
    }
  })

  it('every non-public route has a non-empty allow list', () => {
    for (const route of routeTable) {
      if (route.allow !== 'public') {
        expect(route.allow.length).toBeGreaterThan(0)
      }
    }
  })

  it('public routes use no layout', () => {
    for (const route of routeTable) {
      if (route.allow === 'public') {
        expect(route.layout).toBe('none')
      }
    }
  })
})

describe('missing items route (UX-08)', () => {
  it('admits the China office alongside Nigeria staff and tenant admins, and no other claims route', () => {
    const route = routeTable.find((r) => r.path === '/claims/missing-items')
    expect(route?.allow).toEqual(expect.arrayContaining(['nigeria_office_staff', 'tenant_admin', 'china_office_staff']))
    for (const other of ['/claims', '/claims/seized-items', '/claims/:id']) {
      expect(routeTable.find((r) => r.path === other)?.allow).not.toContain('china_office_staff')
    }
  })
})
