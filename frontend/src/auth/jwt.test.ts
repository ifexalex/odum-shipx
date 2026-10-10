import { describe, expect, it } from 'vitest'
import { buildSession, decodeJwt, sessionFromIdToken } from './jwt'

function fakeJwt(claims: Record<string, unknown>): string {
  const base64url = (input: string): string =>
    btoa(input).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  const header = base64url(JSON.stringify({ alg: 'none' }))
  const payload = base64url(JSON.stringify(claims))
  return `${header}.${payload}.signature`
}

describe('decodeJwt', () => {
  it('decodes the payload segment', () => {
    const token = fakeJwt({ sub: 'user-1', foo: 'bar' })
    expect(decodeJwt(token)).toEqual({ sub: 'user-1', foo: 'bar' })
  })

  it('throws on a malformed token', () => {
    expect(() => decodeJwt('not-a-jwt')).toThrow()
  })
})

describe('buildSession', () => {
  const tenantId = 'aaaa-bbbb'

  it('parses a tenant user from comma-separated groups', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'cognito:groups': `${tenantId}:nigeria_office_staff`,
      exp: 1700000000,
    })
    expect(session.role).toBe('nigeria_office_staff')
    expect(session.tenantId).toBe(tenantId)
    expect(session.isPlatformAdmin).toBe(false)
    expect(session.expiresAt).toBe(1700000000_000)
    expect(session.tokenType).toBe('cognito')
  })

  it('parses groups passed as an unquoted bracketed string', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'cognito:groups': `[${tenantId}:tenant_admin]`,
    })
    expect(session.role).toBe('tenant_admin')
  })

  it('parses groups passed as a real JSON array', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'cognito:groups': [`${tenantId}:china_office_staff`],
    })
    expect(session.role).toBe('china_office_staff')
  })

  it('recognizes the platform_admin group with no tenant prefix', () => {
    const session = buildSession({
      sub: 'admin-1',
      'custom:tenant_id': 'PLATFORM',
      'cognito:groups': 'platform_admin',
    })
    expect(session.role).toBe('platform_admin')
    expect(session.isPlatformAdmin).toBe(true)
  })

  it('falls back to customer when no group matches the tenant', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'cognito:groups': 'some-other-tenant:tenant_admin',
    })
    expect(session.role).toBe('customer')
  })

  it('marks an impersonation session read-only and tags the token type', () => {
    const session = buildSession({
      sub: 'impersonated-user',
      'custom:tenant_id': tenantId,
      'cognito:groups': `${tenantId}:tenant_admin`,
      impersonated_by: 'platform-admin-1',
      session_id: 'sess-1',
      read_only: 'true',
    })
    expect(session.readOnly).toBe(true)
    expect(session.tokenType).toBe('impersonation')
    expect(session.impersonatedBy).toBe('platform-admin-1')
    expect(session.sessionId).toBe('sess-1')
  })

  it('parses a raw ShipX impersonation token (bare tenant_id + role, no groups)', () => {
    // Shape minted by services/tenant_management/impersonation.py — what the
    // frontend receives directly from POST /impersonate (no authorizer mapping).
    const session = buildSession({
      sub: 'target-admin-1',
      tenant_id: tenantId,
      role: 'tenant_admin',
      impersonated_by: 'platform-admin-1',
      session_id: 'sess-2',
      read_only: true,
      exp: Math.floor(Date.now() / 1000) + 1800,
    })
    expect(session.tenantId).toBe(tenantId)
    expect(session.role).toBe('tenant_admin')
    expect(session.readOnly).toBe(true)
    expect(session.tokenType).toBe('impersonation')
  })

  it('throws when required claims are missing', () => {
    expect(() => buildSession({ 'custom:tenant_id': tenantId })).toThrow()
    expect(() => buildSession({ sub: 'user-1' })).toThrow()
  })

  it('collects every matching group into roles, not just the first (multi-role staff support)', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'cognito:groups': `${tenantId}:nigeria_office_staff,${tenantId}:warehouse_attendant`,
    })
    expect(session.roles.sort()).toEqual(['nigeria_office_staff', 'warehouse_attendant'])
  })

  it('uses custom:role for the primary/active role among multiple assigned roles', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'custom:role': 'warehouse_attendant',
      'cognito:groups': `${tenantId}:nigeria_office_staff,${tenantId}:warehouse_attendant`,
    })
    expect(session.role).toBe('warehouse_attendant')
    expect(session.roles.sort()).toEqual(['nigeria_office_staff', 'warehouse_attendant'])
  })

  it('falls back to a deterministic role when custom:role is absent', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'cognito:groups': `${tenantId}:nigeria_office_staff,${tenantId}:warehouse_attendant`,
    })
    // Alphabetically first — 'nigeria_office_staff' < 'warehouse_attendant'.
    expect(session.role).toBe('nigeria_office_staff')
  })

  it('falls back when custom:role names a role the user no longer holds', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'custom:role': 'tenant_admin',
      'cognito:groups': `${tenantId}:nigeria_office_staff,${tenantId}:warehouse_attendant`,
    })
    expect(session.role).toBe('nigeria_office_staff')
  })

  it('single-role sessions get a roles array containing just that role', () => {
    const session = buildSession({
      sub: 'user-1',
      'custom:tenant_id': tenantId,
      'cognito:groups': `${tenantId}:tenant_admin`,
    })
    expect(session.roles).toEqual(['tenant_admin'])
  })
})

describe('sessionFromIdToken', () => {
  it('decodes a JWT end-to-end into a Session', () => {
    const token = fakeJwt({
      sub: 'user-1',
      'custom:tenant_id': 'aaaa-bbbb',
      'cognito:groups': 'aaaa-bbbb:customer',
      exp: 1700000000,
    })
    expect(sessionFromIdToken(token).role).toBe('customer')
  })
})

describe('buildSession — Entra claim shape', () => {
  const tenantId = 'aaaa-bbbb'

  it('reads oid / tenant_id / groups / role from an Entra token', () => {
    const session = buildSession({
      oid: 'entra-obj-1',
      tenant_id: tenantId,
      groups: [`${tenantId}:tenant_admin`, `${tenantId}:china_office_staff`],
      role: 'tenant_admin',
      exp: 1700000000,
    })
    expect(session.userId).toBe('entra-obj-1')
    expect(session.tenantId).toBe(tenantId)
    expect(session.roles.sort()).toEqual(['china_office_staff', 'tenant_admin'])
    expect(session.role).toBe('tenant_admin')
  })

  it('handles a comma-separated Entra groups string', () => {
    const session = buildSession({
      oid: 'entra-obj-2',
      tenant_id: tenantId,
      groups: `${tenantId}:customer`,
      exp: 1700000000,
    })
    expect(session.roles).toEqual(['customer'])
  })
})
