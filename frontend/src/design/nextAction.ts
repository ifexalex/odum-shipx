/**
 * The next step of a record, by status (FD-23): the one action a record's page leads with, in its header. A finished
 * record (released, resolved, picked up) has none. Pages still decide who may take the step (the rules in `api/*Rules`
 * mirror the services' transition checks); this decides what the step is called, so it reads the same everywhere.
 *
 * Checked against the services' transitions on 2026-11-21. Two rows of the audit's draft table do not exist in the
 * product and are left out: an approved refund is processed in the same step (approval pays it or credits it), so
 * there is no "Mark as processed"; and a container at the warehouse is released by pickups, not advanced by hand.
 */
import { nextContainerStatus } from '../api/containerRules'
import type { ContainerStatus } from '../api/tracking'
import { statusLabel } from './status'

export type RecordKind = 'container' | 'packingList' | 'manifest' | 'invoice' | 'releaseNote' | 'dispute' | 'claim' | 'refund'

const NEXT: Record<Exclude<RecordKind, 'container'>, Readonly<Record<string, string>>> = {
  packingList: { draft: 'Submit for approval', pending_approval: 'Approve', rejected: 'Revise and resubmit' },
  manifest: { pending: 'Verify manifest', discrepancies_found: 'Resolve discrepancies' },
  invoice: {
    unpaid: 'Record payment',
    partially_paid: 'Record payment',
    paid: 'Generate release note',
    overpaid: 'Generate release note',
  },
  releaseNote: { active: 'Record pickup' },
  dispute: {
    submitted: 'Acknowledge',
    acknowledged: 'Resolve dispute',
    investigating: 'Resolve dispute',
    escalated_china: 'Resolve dispute',
  },
  claim: {
    filed: 'Start inspection',
    // The service lets a claim be resolved from inspection onwards (claimsRules.canResolveClaim).
    under_inspection: 'Resolve claim',
    inspection_complete: 'Resolve claim',
    pending_resolution: 'Resolve claim',
  },
  refund: { pending_review: 'Complete review', pending_approval: 'Approve refund' },
}

const CONTAINER: Partial<Record<ContainerStatus, string>> = { loading: 'Seal container', sealed: 'Mark in transit' }

/** The next step of a record in `status`, or null when it has none (it is finished, or waits on someone else). */
export function nextActionLabel(kind: RecordKind, status: string): string | null {
  if (kind === 'container') {
    const own = CONTAINER[status as ContainerStatus]
    if (own) return own
    const next = status === 'at_warehouse' ? null : nextContainerStatus(status as ContainerStatus)
    return next ? `Advance to ${statusLabel('container', next)}` : null
  }
  return NEXT[kind][status] ?? null
}
