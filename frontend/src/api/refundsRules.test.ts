import { describe, expect, it } from 'vitest'
import { bankDetailsProblem, canApproveRefund, canRejectRefund, canReviewRefund, isTerminalRefundStatus, refundTypeLabel } from './refundsRules'
import type { Refund } from './refunds'

function _refund(overrides: Partial<Refund> = {}): Refund {
  return {
    id: 'r-001',
    status: 'pending_review',
    refund_type: 'overpayment',
    amount_requested_ngn: '25000',
    amount_approved_ngn: null,
    customer_choice: 'immediate_refund',
    customer_id: 'cust-001',
    billing_id: null,
    damage_claim_id: null,
    reason: 'Overpaid last shipment',
    rejection_reason: null,
    approval_level: 'manager',
    debt_check_passed: null,
    debt_check_notes: null,
    created_at: '2026-07-04T00:00:00Z',
    ...overrides,
  }
}

describe('canReviewRefund', () => {
  it('allows nigeria_office_staff on pending_review', () => {
    expect(canReviewRefund(_refund(), 'nigeria_office_staff')).toBe(true)
  })
  it('blocks tenant_admin', () => {
    expect(canReviewRefund(_refund(), 'tenant_admin')).toBe(false)
  })
  it('blocks when not pending_review', () => {
    expect(canReviewRefund(_refund({ status: 'pending_approval' }), 'nigeria_office_staff')).toBe(false)
  })
})

describe('canApproveRefund', () => {
  it('allows nigeria_office_staff on manager-level pending_approval', () => {
    expect(canApproveRefund(_refund({ status: 'pending_approval', approval_level: 'manager' }), 'nigeria_office_staff')).toBe(true)
  })
  it('allows tenant_admin on head_of_finance', () => {
    expect(canApproveRefund(_refund({ status: 'pending_approval', approval_level: 'head_of_finance' }), 'tenant_admin')).toBe(true)
  })
  it('blocks nigeria_office_staff on head_of_finance', () => {
    expect(canApproveRefund(_refund({ status: 'pending_approval', approval_level: 'head_of_finance' }), 'nigeria_office_staff')).toBe(false)
  })
  it('blocks on wrong status', () => {
    expect(canApproveRefund(_refund({ status: 'pending_review' }), 'nigeria_office_staff')).toBe(false)
  })
  it('blocks customer role', () => {
    expect(canApproveRefund(_refund({ status: 'pending_approval' }), 'customer')).toBe(false)
  })
})

describe('canRejectRefund', () => {
  it('allows nigeria_office_staff on pending_review', () => {
    expect(canRejectRefund(_refund({ status: 'pending_review' }), 'nigeria_office_staff')).toBe(true)
  })
  it('allows tenant_admin on pending_approval', () => {
    expect(canRejectRefund(_refund({ status: 'pending_approval' }), 'tenant_admin')).toBe(true)
  })
  it('blocks on processed', () => {
    expect(canRejectRefund(_refund({ status: 'processed' }), 'tenant_admin')).toBe(false)
  })
})

describe('isTerminalRefundStatus', () => {
  it('flags processed, applied_as_credit, rejected as terminal', () => {
    expect(isTerminalRefundStatus('processed')).toBe(true)
    expect(isTerminalRefundStatus('applied_as_credit')).toBe(true)
    expect(isTerminalRefundStatus('rejected')).toBe(true)
  })
  it('pending states are not terminal', () => {
    expect(isTerminalRefundStatus('pending_review')).toBe(false)
    expect(isTerminalRefundStatus('pending_approval')).toBe(false)
  })
})

describe('refundTypeLabel', () => {
  it('labels the three known refund types', () => {
    expect(refundTypeLabel('overpayment')).toBe('Overpayment refund')
    expect(refundTypeLabel('cbm_correction')).toBe('CBM correction')
    expect(refundTypeLabel('damage_or_loss')).toBe('Damage / loss')
  })

  it('falls back to a generic label rather than rendering nothing', () => {
    // Regression: the switch had no default, so a missing/unmapped value
    // (create_refund_request_for_claim never set refund_type at all, until
    // fixed server-side) returned undefined — React renders that as
    // nothing, silently blanking RefundDetail.tsx's page <h1> for every
    // claim-triggered refund. A generic label is a much less confusing
    // failure mode than an empty heading.
    expect(refundTypeLabel(null as unknown as Refund['refund_type'])).toBe('Refund request')
    expect(refundTypeLabel(undefined as unknown as Refund['refund_type'])).toBe('Refund request')
  })
})

describe('bankDetailsProblem', () => {
  const ok = { bankName: 'Zenith Bank', accountNumber: '0123456789', accountName: 'Ngozi Okonkwo' }
  it('accepts a bank, a 10-digit number and a name', () => expect(bankDetailsProblem(ok)).toBeNull())
  it('needs the bank', () => expect(bankDetailsProblem({ ...ok, bankName: ' ' })).toBe('Enter the name of your bank.'))
  it('needs exactly 10 digits', () => {
    expect(bankDetailsProblem({ ...ok, accountNumber: '012345678' })).toBe('Enter your 10-digit account number.')
    expect(bankDetailsProblem({ ...ok, accountNumber: '01234567890' })).toBe('Enter your 10-digit account number.')
  })
  it('needs the account name', () => expect(bankDetailsProblem({ ...ok, accountName: '' })).toBe('Enter the name on the account.'))
})

