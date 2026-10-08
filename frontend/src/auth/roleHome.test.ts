import { describe, expect, it } from 'vitest'
import { homePathForRole } from './roleHome'
import type { UserRole } from './types'

describe('homePathForRole', () => {
  it.each([
    ['platform_admin', '/platform/dashboard'],
    ['tenant_admin', '/dashboard'],
    ['china_office_staff', '/containers'],
    ['nigeria_office_staff', '/dashboard'],
    ['warehouse_attendant', '/warehouse'],
    ['customer', '/my-shipments'],
  ] satisfies [UserRole, string][])('maps %s to %s', (role, path) => {
    expect(homePathForRole(role)).toBe(path)
  })
})
