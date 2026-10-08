import { describe, expect, it } from 'vitest'
import { canResolveDiscrepancy, canRevokeVerification, canVerifyManifest } from './manifestRules'
import type { Manifest } from './manifest'

function buildManifest(overrides: Partial<Manifest> = {}): Manifest {
  return {
    id: 'mf1',
    tenant_id: 't1',
    container_id: 'c1',
    container_number: 'HLBU9384712',
    container_status: 'loading',
    total_customers: 0,
    total_cartons: 0,
    total_weight_kg: '0',
    total_cbm: '0',
    verification_status: 'pending',
    verified_by: null,
    verified_at: null,
    notes: null,
    customers: [],
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
    ...overrides,
  }
}

describe('canVerifyManifest', () => {
  it('allows china_office_staff and nigeria_office_staff on a pending manifest', () => {
    const mf = buildManifest({ verification_status: 'pending' })
    expect(canVerifyManifest(mf, 'china_office_staff')).toBe(true)
    expect(canVerifyManifest(mf, 'nigeria_office_staff')).toBe(true)
  })

  it('blocks tenant_admin and other roles', () => {
    const mf = buildManifest({ verification_status: 'pending' })
    expect(canVerifyManifest(mf, 'tenant_admin')).toBe(false)
    expect(canVerifyManifest(mf, 'customer')).toBe(false)
  })

  it('blocks verification outside pending status', () => {
    expect(canVerifyManifest(buildManifest({ verification_status: 'verified' }), 'china_office_staff')).toBe(false)
    expect(
      canVerifyManifest(buildManifest({ verification_status: 'discrepancies_found' }), 'nigeria_office_staff'),
    ).toBe(false)
  })
})

describe('canResolveDiscrepancy', () => {
  it('allows nigeria_office_staff and tenant_admin on a discrepancies_found manifest', () => {
    const mf = buildManifest({ verification_status: 'discrepancies_found' })
    expect(canResolveDiscrepancy(mf, 'nigeria_office_staff')).toBe(true)
    expect(canResolveDiscrepancy(mf, 'tenant_admin')).toBe(true)
  })

  it('blocks china_office_staff — verify-only, not resolve', () => {
    const mf = buildManifest({ verification_status: 'discrepancies_found' })
    expect(canResolveDiscrepancy(mf, 'china_office_staff')).toBe(false)
  })

  it('blocks resolution outside discrepancies_found status', () => {
    expect(canResolveDiscrepancy(buildManifest({ verification_status: 'pending' }), 'tenant_admin')).toBe(false)
    expect(canResolveDiscrepancy(buildManifest({ verification_status: 'resolved' }), 'tenant_admin')).toBe(false)
  })
})

describe('canRevokeVerification', () => {
  it('allows all staff roles on a verified manifest', () => {
    const mf = buildManifest({ verification_status: 'verified' })
    expect(canRevokeVerification(mf, 'china_office_staff')).toBe(true)
    expect(canRevokeVerification(mf, 'nigeria_office_staff')).toBe(true)
    expect(canRevokeVerification(mf, 'tenant_admin')).toBe(true)
  })

  it('blocks customer and warehouse roles', () => {
    const mf = buildManifest({ verification_status: 'verified' })
    expect(canRevokeVerification(mf, 'customer')).toBe(false)
    expect(canRevokeVerification(mf, 'warehouse_attendant')).toBe(false)
  })

  it('blocks revocation outside verified status', () => {
    expect(canRevokeVerification(buildManifest({ verification_status: 'pending' }), 'nigeria_office_staff')).toBe(false)
    expect(canRevokeVerification(buildManifest({ verification_status: 'discrepancies_found' }), 'tenant_admin')).toBe(false)
    expect(canRevokeVerification(buildManifest({ verification_status: 'resolved' }), 'nigeria_office_staff')).toBe(false)
  })

  it('blocks revocation once container has advanced past loading', () => {
    const verified: Partial<Manifest> = { verification_status: 'verified' }
    expect(canRevokeVerification(buildManifest({ ...verified, container_status: 'sealed' }), 'nigeria_office_staff')).toBe(false)
    expect(canRevokeVerification(buildManifest({ ...verified, container_status: 'in_transit' }), 'tenant_admin')).toBe(false)
    expect(canRevokeVerification(buildManifest({ ...verified, container_status: 'loading' }), 'nigeria_office_staff')).toBe(true)
  })
})
