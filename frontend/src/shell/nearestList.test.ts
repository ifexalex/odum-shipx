import { describe, expect, it } from 'vitest'
import { nearestList } from './nearestList'

describe('nearestList (FD-55)', () => {
  it('is the closest list above the address that the user may open', () => {
    expect(nearestList('/billing/x/y', ['nigeria_office_staff'], '/dashboard')).toEqual({ to: '/billing', label: 'Billing' })
    expect(nearestList('/admin/config/nope', ['tenant_admin'], '/dashboard')).toEqual({
      to: '/admin/config',
      label: 'Settings',
    })
  })

  it('skips a list the user may not open', () => {
    expect(nearestList('/billing/x', ['warehouse_attendant'], '/warehouse')).toBeNull()
  })

  it('is nothing when the nearest list is the home page, or there is none', () => {
    expect(nearestList('/dashboard/x', ['tenant_admin'], '/dashboard')).toBeNull()
    expect(nearestList('/nowhere/at/all', ['tenant_admin'], '/dashboard')).toBeNull()
  })
})
