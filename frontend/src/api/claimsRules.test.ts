import { describe, expect, it } from 'vitest'
import {
  CLAIM_STATUS_ORDER,
  CUSTOMER_CLAIM_STATUS_LABELS,
  canFileClaim,
  canResolveClaim,
  canStartInspection,
  canUpdateItem,
  customerInspectionLabel,
  customerRefundLabel,
  customerResolutionLabel,
  isTerminalClaimStatus,
} from './claimsRules'
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

describe('customer-facing claim wording (UX-07)', () => {
  it('has a label for every claim status, in progress order', () => {
    expect(CLAIM_STATUS_ORDER.map((s) => CUSTOMER_CLAIM_STATUS_LABELS[s])).toEqual([
      'Filed',
      'Under inspection',
      'Inspection complete',
      'Pending resolution',
      'Resolved',
      'Closed',
    ])
  })

  it('says how a claim was checked, and that it has not been yet', () => {
    expect(customerInspectionLabel('customer_evidence')).toBe('From the photos and videos you provided')
    expect(customerInspectionLabel('delegate_visit')).toBe('An agent inspected the goods in person')
    expect(customerInspectionLabel(null)).toBe('Not started yet')
  })

  it('says what was decided', () => {
    const base = { amount_ngn: null, discount_percentage: null, resolved_at: 'x' }
    expect(customerResolutionLabel({ ...base, resolution_type: 'refund' })).toBe('Refund')
    expect(customerResolutionLabel({ ...base, resolution_type: 'compensation' })).toBe('Compensation')
    expect(customerResolutionLabel({ ...base, resolution_type: 'no_action' })).toBe('Closed without a payout')
    expect(customerResolutionLabel({ ...base, resolution_type: 'discount', discount_percentage: '15.00' })).toBe('15% discount')
    expect(customerResolutionLabel({ ...base, resolution_type: 'discount' })).toBe('Discount')
  })

  it('collapses the refund pipeline into what a customer needs to know', () => {
    for (const review of ['pending_review', 'accounts_reviewed', 'pending_approval']) {
      expect(customerRefundLabel(review)).toBe('Being reviewed')
    }
    expect(customerRefundLabel('approved')).toBe('Approved: the payout is being arranged')
    expect(customerRefundLabel('processed')).toBe('Paid')
    expect(customerRefundLabel('applied_as_credit')).toBe('Applied as credit to your account')
    expect(customerRefundLabel('rejected')).toBe('Not approved')
  })

  it('does not break on a status it has not heard of', () => {
    expect(customerRefundLabel('some_future_status')).toBe('Being reviewed')
  })
})
