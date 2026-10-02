import { describe, expect, it } from 'vitest'
import { canCreateReleaseNote, canRecordPickup, canSplitNote, isTerminalReleaseStatus } from './releaseNotesRules'
import type { ReleaseNote } from './releaseNotes'

function _note(overrides: Partial<ReleaseNote> = {}): ReleaseNote {
  return {
    id: 'rn-001', reference_number: 'ACME-RN-20260704-0001',
    customer_name: 'Chioma Eze', container_number: 'ACME001001',
    carton_count: 3, total_cartons_for_customer: 5,
    is_partial_release: true, carton_tags: ['A', 'B', 'C'],
    payment_status: 'paid', status: 'active',
    authorized_at: '2026-07-04T10:00:00Z', warehouse_address: null,
    packages_released: null, package_unit: null, packages_balance: null,
    warehouse_name: null, warehouse_phone: null, is_on_credit: false,
    credit_granted_by_name: null, receipt_number: null,
    physical_document_number: null, packing_list_invoice_numbers: [],
    amount_paid_ngn: '0', balance_ngn: '0', total_ngn: '0', debt_due_date: null,
    ...overrides,
  }
}

describe('canRecordPickup', () => {
  it('allows warehouse_attendant on active', () => {
    expect(canRecordPickup(_note(), 'warehouse_attendant')).toBe(true)
  })
  it('blocks nigeria_office_staff', () => {
    expect(canRecordPickup(_note(), 'nigeria_office_staff')).toBe(false)
  })
  it('blocks on non-active status', () => {
    expect(canRecordPickup(_note({ status: 'picked_up' }), 'warehouse_attendant')).toBe(false)
  })
})

describe('canSplitNote', () => {
  it('allows nigeria_office_staff on active', () => {
    expect(canSplitNote(_note(), 'nigeria_office_staff')).toBe(true)
  })
  it('allows tenant_admin on active', () => {
    expect(canSplitNote(_note(), 'tenant_admin')).toBe(true)
  })
  it('blocks warehouse_attendant', () => {
    expect(canSplitNote(_note(), 'warehouse_attendant')).toBe(false)
  })
  it('blocks when note is picked_up', () => {
    expect(canSplitNote(_note({ status: 'picked_up' }), 'nigeria_office_staff')).toBe(false)
  })
})

describe('canCreateReleaseNote', () => {
  it('allows nigeria_office_staff', () => {
    expect(canCreateReleaseNote('nigeria_office_staff')).toBe(true)
  })
  it('allows tenant_admin', () => {
    expect(canCreateReleaseNote('tenant_admin')).toBe(true)
  })
  it('blocks warehouse_attendant', () => {
    expect(canCreateReleaseNote('warehouse_attendant')).toBe(false)
  })
})

describe('isTerminalReleaseStatus', () => {
  it('flags picked_up, expired, cancelled as terminal', () => {
    expect(isTerminalReleaseStatus('picked_up')).toBe(true)
    expect(isTerminalReleaseStatus('expired')).toBe(true)
    expect(isTerminalReleaseStatus('cancelled')).toBe(true)
  })
  it('active is not terminal', () => {
    expect(isTerminalReleaseStatus('active')).toBe(false)
  })
})
