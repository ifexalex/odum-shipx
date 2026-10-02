import { describe, expect, it } from 'vitest'
import type { PackingList } from './packingList'
import {
  canApproveOrReject,
  canEditPackingList,
  canSubmitForApproval,
  computeCbm,
  dominantPackageUnit,
  explainBulkFailure,
  formatPackageMix,
  groupBulkFailures,
  isSelfApproval,
  totalDeclaredValueUsd,
} from './packingListRules'

function buildPl(overrides: Partial<PackingList> = {}): PackingList {
  return {
    id: 'pl1',
    tenant_id: 't1',
    container_id: 'c1',
    container_number: 'ACME-001',
    customer_id: 'cust1',
    status: 'draft',
    items: [],
    total_cbm: '0',
    total_weight_kg: '0',
    carton_count: 0,
    created_by: 'staff-1',
    approved_by: null,
    approved_at: null,
    rejected_by: null,
    rejected_at: null,
    approval_comments: null,
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
    ...overrides,
  }
}

describe('canEditPackingList', () => {
  it('allows editing draft and rejected lists', () => {
    expect(canEditPackingList(buildPl({ status: 'draft' }))).toBe(true)
    expect(canEditPackingList(buildPl({ status: 'rejected' }))).toBe(true)
  })

  it('blocks editing pending_approval and approved lists', () => {
    expect(canEditPackingList(buildPl({ status: 'pending_approval' }))).toBe(false)
    expect(canEditPackingList(buildPl({ status: 'approved' }))).toBe(false)
  })
})

describe('canSubmitForApproval', () => {
  it('requires draft status and at least one item', () => {
    const itemStub = {
      id: 'i1',
      packing_list_id: 'pl1',
      description: 'box',
      weight_dispatch_kg: null,
      weight_actual_kg: null,
      carton_tag: null,
      tracking_code: null,
      cbm: null,
      length_cm: null,
      width_cm: null,
      height_cm: null,
      received_date: null,
      declared_value_usd: null,
    }
    expect(canSubmitForApproval(buildPl({ status: 'draft', items: [] }))).toBe(false)
    expect(canSubmitForApproval(buildPl({ status: 'draft', items: [itemStub] }))).toBe(true)
    expect(canSubmitForApproval(buildPl({ status: 'pending_approval', items: [itemStub] }))).toBe(false)
  })
})

describe('isSelfApproval', () => {
  it('matches when the actor created the list', () => {
    expect(isSelfApproval(buildPl({ created_by: 'staff-1' }), 'staff-1')).toBe(true)
    expect(isSelfApproval(buildPl({ created_by: 'staff-1' }), 'staff-2')).toBe(false)
  })

  it('is false when created_by is missing', () => {
    expect(isSelfApproval(buildPl({ created_by: null }), 'staff-1')).toBe(false)
  })
})

describe('canApproveOrReject', () => {
  it('allows china_office_staff and tenant_admin on pending lists they did not create', () => {
    const pl = buildPl({ status: 'pending_approval', created_by: 'staff-1' })
    expect(canApproveOrReject(pl, 'china_office_staff', 'staff-2')).toBe(true)
    expect(canApproveOrReject(pl, 'tenant_admin', 'admin-1')).toBe(true)
  })

  it('blocks self-approval even for an authorized role', () => {
    const pl = buildPl({ status: 'pending_approval', created_by: 'staff-1' })
    expect(canApproveOrReject(pl, 'china_office_staff', 'staff-1')).toBe(false)
  })

  it('blocks roles outside the approver set', () => {
    const pl = buildPl({ status: 'pending_approval', created_by: 'staff-1' })
    expect(canApproveOrReject(pl, 'nigeria_office_staff', 'staff-2')).toBe(false)
    expect(canApproveOrReject(pl, 'customer', 'staff-2')).toBe(false)
  })

  it('blocks approval outside pending_approval status', () => {
    const pl = buildPl({ status: 'draft', created_by: 'staff-1' })
    expect(canApproveOrReject(pl, 'tenant_admin', 'admin-1')).toBe(false)
  })
})

describe('computeCbm', () => {
  it('matches the documented mockup figures', () => {
    expect(computeCbm(40, 30, 25)).toBeCloseTo(0.03, 5)
    expect(computeCbm(35, 30, 20)).toBeCloseTo(0.021, 5)
  })
})

describe('totalDeclaredValueUsd', () => {
  it('sums declared values, treating missing values as zero', () => {
    // declared_value_usd is a DECIMAL column — always a string on the wire
    // (see packingList.ts). Using string fixtures here guards against the
    // naive `sum + item.declared_value_usd` bug, which silently does string
    // concatenation ("0" + "380.00") instead of numeric addition.
    const pl = buildPl({
      items: [
        { id: 'i1', packing_list_id: 'pl1', description: 'a', weight_dispatch_kg: null, weight_actual_kg: null, carton_tag: null, tracking_code: null, cbm: null, length_cm: null, width_cm: null, height_cm: null, received_date: null, declared_value_usd: '380.00' },
        { id: 'i2', packing_list_id: 'pl1', description: 'b', weight_dispatch_kg: null, weight_actual_kg: null, carton_tag: null, tracking_code: null, cbm: null, length_cm: null, width_cm: null, height_cm: null, received_date: null, declared_value_usd: null },
      ],
    })
    expect(totalDeclaredValueUsd(pl)).toBe(380)
  })
})

describe('explainBulkFailure', () => {
  it('turns the self-approval code into something a user can act on', () => {
    const { title, help } = explainBulkFailure('self_approval_forbidden')
    // The raw code must not leak to the screen.
    expect(title).not.toContain('self_approval_forbidden')
    expect(title.toLowerCase()).toContain('cannot approve')
    expect(help.toLowerCase()).toContain('colleague')
  })

  it('explains each wrong_status variant with the next step', () => {
    expect(explainBulkFailure('wrong_status:draft').help).toMatch(/submit for approval/i)
    expect(explainBulkFailure('wrong_status:approved').title).toMatch(/already approved/i)
    expect(explainBulkFailure('wrong_status:rejected').help).toMatch(/submit it again/i)
    expect(explainBulkFailure('wrong_status:pending_approval').title).toMatch(/already waiting/i)
  })

  it('falls back to showing an unknown code rather than hiding the failure', () => {
    const { title } = explainBulkFailure('some_new_backend_code')
    expect(title).toBe('some_new_backend_code')
  })
})

describe('groupBulkFailures', () => {
  it('collapses many failures sharing a reason into one group', () => {
    const failures = [
      { id: 'a', reason: 'self_approval_forbidden' },
      { id: 'b', reason: 'self_approval_forbidden' },
      { id: 'c', reason: 'wrong_status:draft' },
    ]
    const groups = groupBulkFailures(failures)
    expect(groups).toHaveLength(2)
    expect(groups.find((g) => g.reason === 'self_approval_forbidden')?.ids).toEqual(['a', 'b'])
  })

  it('returns nothing for an empty list', () => {
    expect(groupBulkFailures([])).toEqual([])
  })
})

describe('formatPackageMix', () => {
  it('names each unit and leads with the largest group', () => {
    // A bare "3" cannot tell staff whether they are looking at bales or bags.
    expect(formatPackageMix({ bale: 2, bag: 16 })).toBe('16 bags · 2 bales')
  })

  it('uses the singular form for one', () => {
    expect(formatPackageMix({ bale: 1 })).toBe('1 bale')
    expect(formatPackageMix({ pallet: 1, carton: 1 })).toMatch(/1 pallet|1 carton/)
  })

  it('shows a dash rather than an empty cell when nothing is known', () => {
    expect(formatPackageMix({})).toBe('—')
    expect(formatPackageMix(null)).toBe('—')
  })

  it('labels rows that carried no unit as items instead of dropping them', () => {
    expect(formatPackageMix({ unspecified: 4 })).toBe('4 items')
  })
})

describe('dominantPackageUnit', () => {
  it('names the unit when a list is all one kind, and null when genuinely mixed', () => {
    expect(dominantPackageUnit({ bale: 18 })).toBe('bale')
    expect(dominantPackageUnit({ bale: 2, bag: 16 })).toBeNull()
    expect(dominantPackageUnit({})).toBeNull()
  })
})
