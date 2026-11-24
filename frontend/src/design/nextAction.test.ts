import { describe, expect, it } from 'vitest'
import { nextActionLabel, type RecordKind } from './nextAction'
import { statusesOf } from './status'

describe('the next step of a record (FD-23)', () => {
  it.each([
    ['container', 'loading', 'Seal container'],
    ['container', 'sealed', 'Mark in transit'],
    ['container', 'in_transit', 'Advance to Arrived in Nigeria'],
    ['container', 'arrived', 'Advance to Customs clearance'],
    ['container', 'customs_clearance', 'Advance to Cleared'],
    ['container', 'cleared', 'Advance to At warehouse'],
    ['packingList', 'draft', 'Submit for approval'],
    ['packingList', 'pending_approval', 'Approve'],
    ['packingList', 'rejected', 'Revise and resubmit'],
    ['manifest', 'pending', 'Verify manifest'],
    ['manifest', 'discrepancies_found', 'Resolve discrepancies'],
    ['invoice', 'unpaid', 'Record payment'],
    ['invoice', 'partially_paid', 'Record payment'],
    ['invoice', 'paid', 'Generate release note'],
    ['invoice', 'overpaid', 'Generate release note'],
    ['releaseNote', 'active', 'Record pickup'],
    ['dispute', 'submitted', 'Acknowledge'],
    ['dispute', 'acknowledged', 'Resolve dispute'],
    ['dispute', 'escalated_china', 'Resolve dispute'],
    ['claim', 'filed', 'Start inspection'],
    ['claim', 'pending_resolution', 'Resolve claim'],
    ['refund', 'pending_review', 'Complete review'],
    ['refund', 'pending_approval', 'Approve refund'],
  ] as const)('%s %s → %s', (kind, status, label) => {
    expect(nextActionLabel(kind, status)).toBe(label)
  })

  it.each([
    ['container', ['at_warehouse', 'fully_released', 'cancelled']],
    ['packingList', ['approved']],
    ['manifest', ['verified', 'resolved']],
    ['invoice', ['waived', 'cancelled', 'released_with_outstanding']],
    ['releaseNote', ['picked_up', 'expired', 'cancelled']],
    ['dispute', ['resolved_adjusted', 'resolved_no_change', 'closed']],
    ['claim', ['resolved', 'closed']],
    ['refund', ['approved', 'rejected', 'processed', 'applied_as_credit']],
  ] as const)('a finished %s has no next step', (kind, statuses) => {
    for (const status of statuses) expect(nextActionLabel(kind as RecordKind, status), status).toBeNull()
  })

  it('every status of every record kind is covered: a step or deliberately none', () => {
    const kinds: Array<[RecordKind, Parameters<typeof statusesOf>[0]]> = [
      ['container', 'container'],
      ['packingList', 'packingList'],
      ['manifest', 'manifest'],
      ['invoice', 'invoice'],
      ['releaseNote', 'releaseNote'],
      ['dispute', 'dispute'],
      ['claim', 'claim'],
      ['refund', 'refund'],
    ]
    for (const [kind, registry] of kinds) {
      for (const status of statusesOf(registry)) {
        const label = nextActionLabel(kind, status)
        expect(label === null || label.length > 0, `${kind} ${status}`).toBe(true)
      }
    }
  })
})
