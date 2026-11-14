import { describe, expect, it } from 'vitest'
import {
  canAcknowledgeDispute,
  canApplyCarryover,
  canCancelBilling,
  canGenerateInvoices,
  canRecordPayment,
  canRejectDispute,
  canResolveDispute,
  groupUnbilledByContainer,
  isTerminalDisputeStatus,
} from './billingRules'
import type { Billing, CBMDispute, UnbilledCustomer } from './billing'

function makeBilling(overrides: Partial<Billing> = {}): Billing {
  return {
    id: 'b1',
    container_id: 'c1',
    container_number: 'ACME-001',
    total_cbm: '2.5',
    cbm_rate_usd: '45',
    dollar_rate: '1550',
    subtotal_usd: '112.50',
    subtotal_ngn: '174375',
    misc_fees: [],
    misc_fees_ngn: 0,
    adjustments_ngn: '0',
    carryover_ngn: 0,
    storage_fees_ngn: 0,
    total_due_ngn: '174375',
    total_paid_ngn: '0',
    outstanding_ngn: '174375',
    payment_status: 'unpaid',
    released_with_outstanding: false,
    billed_at: null,
    payments: [],
    carryovers: [],
    _active_disputes: [],
    ...overrides,
  }
}

function makeDispute(overrides: Partial<CBMDispute> = {}): CBMDispute {
  return {
    id: 'd1',
    billing_id: 'b1',
    original_cbm: '2.5',
    corrected_cbm: null,
    status: 'submitted',
    submitted_at: '2026-06-01T10:00:00Z',
    ...overrides,
  }
}

describe('canRecordPayment', () => {
  it('allows nigeria on unpaid billing', () => {
    expect(canRecordPayment(makeBilling({ payment_status: 'unpaid' }), 'nigeria_office_staff')).toBe(true)
  })
  it('allows tenant_admin on partially_paid billing', () => {
    expect(canRecordPayment(makeBilling({ payment_status: 'partially_paid' }), 'tenant_admin')).toBe(true)
  })
  it('blocks nigeria on paid billing', () => {
    expect(canRecordPayment(makeBilling({ payment_status: 'paid' }), 'nigeria_office_staff')).toBe(false)
  })
  it('blocks china_office_staff always', () => {
    expect(canRecordPayment(makeBilling({ payment_status: 'unpaid' }), 'china_office_staff')).toBe(false)
  })
})

describe('canCancelBilling', () => {
  it('allows on unpaid', () => expect(canCancelBilling(makeBilling({ payment_status: 'unpaid' }), 'nigeria_office_staff')).toBe(true))
  it('blocks on paid', () => expect(canCancelBilling(makeBilling({ payment_status: 'paid' }), 'nigeria_office_staff')).toBe(false))
  it('blocks on waived', () => expect(canCancelBilling(makeBilling({ payment_status: 'waived' }), 'tenant_admin')).toBe(false))
})

describe('canApplyCarryover', () => {
  it('allows on unpaid', () => expect(canApplyCarryover(makeBilling({ payment_status: 'unpaid' }), 'nigeria_office_staff')).toBe(true))
  it('blocks on cancelled', () => expect(canApplyCarryover(makeBilling({ payment_status: 'cancelled' }), 'nigeria_office_staff')).toBe(false))
  it('blocks on waived', () => expect(canApplyCarryover(makeBilling({ payment_status: 'waived' }), 'tenant_admin')).toBe(false))
})

describe('canAcknowledgeDispute', () => {
  it('allows nigeria on submitted dispute', () => expect(canAcknowledgeDispute(makeDispute({ status: 'submitted' }), 'nigeria_office_staff')).toBe(true))
  it('blocks nigeria on acknowledged dispute', () => expect(canAcknowledgeDispute(makeDispute({ status: 'acknowledged' }), 'nigeria_office_staff')).toBe(false))
  it('blocks tenant_admin', () => expect(canAcknowledgeDispute(makeDispute({ status: 'submitted' }), 'tenant_admin')).toBe(false))
})

describe('canResolveDispute', () => {
  it('allows nigeria on submitted', () => expect(canResolveDispute(makeDispute({ status: 'submitted' }), 'nigeria_office_staff')).toBe(true))
  it('allows china on escalated_china', () => expect(canResolveDispute(makeDispute({ status: 'escalated_china' }), 'china_office_staff')).toBe(true))
  it('allows tenant_admin on investigating', () => expect(canResolveDispute(makeDispute({ status: 'investigating' }), 'tenant_admin')).toBe(true))
  it('blocks on resolved_no_change (terminal)', () => expect(canResolveDispute(makeDispute({ status: 'resolved_no_change' }), 'nigeria_office_staff')).toBe(false))
})

describe('canRejectDispute', () => {
  it('matches canResolve for eligible roles/statuses', () => {
    expect(canRejectDispute(makeDispute({ status: 'submitted' }), 'nigeria_office_staff')).toBe(true)
    expect(canRejectDispute(makeDispute({ status: 'closed' }), 'nigeria_office_staff')).toBe(false)
  })
})

describe('isTerminalDisputeStatus', () => {
  it('flags terminal statuses', () => {
    expect(isTerminalDisputeStatus('resolved_adjusted')).toBe(true)
    expect(isTerminalDisputeStatus('resolved_no_change')).toBe(true)
    expect(isTerminalDisputeStatus('closed')).toBe(true)
    expect(isTerminalDisputeStatus('submitted')).toBe(false)
    expect(isTerminalDisputeStatus('investigating')).toBe(false)
  })
})

describe('canGenerateInvoices', () => {
  it.each(['nigeria_office_staff', 'tenant_admin'] as const)('allows %s', (role) => {
    expect(canGenerateInvoices(role)).toBe(true)
  })

  it.each(['china_office_staff', 'warehouse_attendant', 'customer'] as const)('refuses %s', (role) => {
    expect(canGenerateInvoices(role)).toBe(false)
  })
})

describe('groupUnbilledByContainer', () => {
  function row(overrides: Partial<UnbilledCustomer>): UnbilledCustomer {
    return {
      container_id: 'k1',
      container_number: 'ACME001',
      container_status: 'cleared',
      customer_id: 'c1',
      customer_name: 'Alice',
      total_cbm: '2.000',
      ...overrides,
    }
  }

  it('returns nothing for no rows', () => {
    expect(groupUnbilledByContainer([])).toEqual([])
  })

  it('groups customers under their container and totals the CBM', () => {
    const groups = groupUnbilledByContainer([
      row({}),
      row({ container_id: 'k2', container_number: 'ACME002', customer_id: 'c3', customer_name: 'Chi', total_cbm: 4 }),
      row({ customer_id: 'c2', customer_name: 'Bob', total_cbm: '1.500' }),
    ])

    expect(groups).toEqual([
      {
        containerId: 'k1',
        containerNumber: 'ACME001',
        customers: [
          { id: 'c1', name: 'Alice', cbm: 2 },
          { id: 'c2', name: 'Bob', cbm: 1.5 },
        ],
        totalCbm: 3.5,
      },
      { containerId: 'k2', containerNumber: 'ACME002', customers: [{ id: 'c3', name: 'Chi', cbm: 4 }], totalCbm: 4 },
    ])
  })

  it('names a customer with no name, and counts unparseable CBM as zero', () => {
    const groups = groupUnbilledByContainer([row({ customer_name: null, total_cbm: 'n/a' })])

    expect(groups).toEqual([
      { containerId: 'k1', containerNumber: 'ACME001', customers: [{ id: 'c1', name: 'Customer', cbm: 0 }], totalCbm: 0 },
    ])
  })
})
