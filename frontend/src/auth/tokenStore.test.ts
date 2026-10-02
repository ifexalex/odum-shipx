import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearActiveTokens,
  getActiveIdToken,
  getActiveTokenType,
  getAuthHeaders,
  setActiveLocalAuth,
  setActiveTokens,
} from './tokenStore'

describe('tokenStore', () => {
  beforeEach(() => {
    clearActiveTokens()
  })

  it('returns no headers when nothing is active', () => {
    expect(getAuthHeaders()).toEqual({})
    expect(getActiveIdToken()).toBeNull()
    expect(getActiveTokenType()).toBeNull()
  })

  it('exposes a bearer header for a normal cognito session', () => {
    setActiveTokens({ idToken: 'id-1', tokenType: 'cognito' })
    expect(getAuthHeaders()).toEqual({ Authorization: 'Bearer id-1' })
    expect(getActiveIdToken()).toBe('id-1')
    expect(getActiveTokenType()).toBe('cognito')
  })

  it('adds X-Token-Type for an impersonation session', () => {
    setActiveTokens({ idToken: 'id-imp', tokenType: 'impersonation' })
    expect(getAuthHeaders()).toEqual({ Authorization: 'Bearer id-imp', 'X-Token-Type': 'impersonation' })
  })

  it('exposes the local dev header trio instead of a bearer token', () => {
    setActiveLocalAuth({ tenantId: 'PLATFORM', role: 'platform_admin', roles: ['platform_admin'], userId: 'local-user' })
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': 'PLATFORM',
      'X-Role': 'platform_admin',
      'X-User-ID': 'local-user',
    })
    expect(getActiveIdToken()).toBeNull()
  })

  it('adds X-Roles for a multi-role local dev identity', () => {
    setActiveLocalAuth({
      tenantId: 't1',
      role: 'nigeria_office_staff',
      roles: ['nigeria_office_staff', 'warehouse_attendant'],
      userId: 'local-multi',
    })
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': 't1',
      'X-Role': 'nigeria_office_staff',
      'X-Roles': 'nigeria_office_staff,warehouse_attendant',
      'X-User-ID': 'local-multi',
    })
  })

  it('omits X-Roles for a single-role local dev identity', () => {
    setActiveLocalAuth({ tenantId: 't1', role: 'tenant_admin', roles: ['tenant_admin'], userId: 'local-admin' })
    expect(getAuthHeaders()).not.toHaveProperty('X-Roles')
  })

  it('clears active tokens', () => {
    setActiveTokens({ idToken: 'id-1', tokenType: 'cognito' })
    clearActiveTokens()
    expect(getAuthHeaders()).toEqual({})
  })
})
