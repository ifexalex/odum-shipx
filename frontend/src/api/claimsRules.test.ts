import { describe, expect, it } from 'vitest'
import { canFileClaim, canResolveClaim, canStartInspection, canUpdateItem, isTerminalClaimStatus } from './claimsRules'
import type { Claim } from './claims'

function makeClaim(status: Claim['status']): Claim {
  return {
    id: 'c1',
    reference: 'DC-20260601-001',
    status,
    container_id: null,
    container_number: null,
    customer_id: null,
    customer_name: null,
    description: 'stub',
    inspection_method: null,
    cartons_affected: [],
    upload_urls: null,
    created_at: '2026-06-01T10:00:00Z',
  }
}

describe('canStartInspection', () => {
  it('allows nigeria on filed claim', () => expect(canStartInspection(makeClaim('filed'), 'nigeria_office_staff')).toBe(true))
  it('blocks nigeria on under_inspection', () => expect(canStartInspection(makeClaim('under_inspection'), 'nigeria_office_staff')).toBe(false))
  it('blocks tenant_admin', () => expect(canStartInspection(makeClaim('filed'), 'tenant_admin')).toBe(false))
})

describe('canResolveClaim', () => {
  it('allows nigeria on under_inspection', () => expect(canResolveClaim(makeClaim('under_inspection'), 'nigeria_office_staff')).toBe(true))
  it('allows tenant_admin on pending_resolution', () => expect(canResolveClaim(makeClaim('pending_resolution'), 'tenant_admin')).toBe(true))
  it('blocks on filed (not yet inspected)', () => expect(canResolveClaim(makeClaim('filed'), 'nigeria_office_staff')).toBe(false))
  it('blocks on resolved (terminal)', () => expect(canResolveClaim(makeClaim('resolved'), 'nigeria_office_staff')).toBe(false))
})

describe('canFileClaim', () => {
  it('allows nigeria', () => expect(canFileClaim('nigeria_office_staff')).toBe(true))
  it('allows customer', () => expect(canFileClaim('customer')).toBe(true))
  it('blocks tenant_admin', () => expect(canFileClaim('tenant_admin')).toBe(false))
  it('blocks china', () => expect(canFileClaim('china_office_staff')).toBe(false))
})

describe('canUpdateItem', () => {
  it('allows nigeria', () => expect(canUpdateItem('nigeria_office_staff')).toBe(true))
  it('blocks tenant_admin', () => expect(canUpdateItem('tenant_admin')).toBe(false))
})

describe('isTerminalClaimStatus', () => {
  it('flags resolved and closed as terminal', () => {
    expect(isTerminalClaimStatus('resolved')).toBe(true)
    expect(isTerminalClaimStatus('closed')).toBe(true)
    expect(isTerminalClaimStatus('filed')).toBe(false)
    expect(isTerminalClaimStatus('pending_resolution')).toBe(false)
  })
})
