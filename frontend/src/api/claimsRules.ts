import type { UserRole } from '../auth/types'
import type { Claim } from './claims'

const _INSPECT_ROLES: UserRole[] = ['nigeria_office_staff']
const _RESOLVE_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const _FILE_CLAIM_ROLES: UserRole[] = ['nigeria_office_staff', 'customer']
const _ITEM_WRITE_ROLES: UserRole[] = ['nigeria_office_staff']

export function canStartInspection(claim: Claim, role: UserRole): boolean {
  return _INSPECT_ROLES.includes(role) && claim.status === 'filed'
}

export function canResolveClaim(claim: Claim, role: UserRole): boolean {
  const resolvable: Claim['status'][] = ['under_inspection', 'inspection_complete', 'pending_resolution']
  return _RESOLVE_ROLES.includes(role) && resolvable.includes(claim.status)
}

export function canFileClaim(role: UserRole): boolean {
  return _FILE_CLAIM_ROLES.includes(role)
}

export function canUpdateItem(role: UserRole): boolean {
  return _ITEM_WRITE_ROLES.includes(role)
}

export function isTerminalClaimStatus(status: Claim['status']): boolean {
  return status === 'resolved' || status === 'closed'
}

export const CLAIM_STATUS_ORDER: Claim['status'][] = [
  'filed',
  'under_inspection',
  'inspection_complete',
  'pending_resolution',
  'resolved',
  'closed',
]

// ---------------------------------------------------------------------------
// Customer-facing wording (the customer portal's claim pages)
// ---------------------------------------------------------------------------

export const CUSTOMER_CLAIM_STATUS_LABELS: Record<Claim['status'], string> = {
  filed: 'Filed',
  under_inspection: 'Under inspection',
  inspection_complete: 'Inspection complete',
  pending_resolution: 'Pending resolution',
  resolved: 'Resolved',
  closed: 'Closed',
}

/** How the claim was checked, in words for the customer. */
export function customerInspectionLabel(method: Claim['inspection_method']): string {
  switch (method) {
    case 'customer_evidence':
      return 'From the photos and videos you provided'
    case 'delegate_visit':
      return 'An agent inspected the goods in person'
    default:
      return 'Not started yet'
  }
}

/** What was decided, in words for the customer. */
export function customerResolutionLabel(resolution: NonNullable<Claim['resolution']>): string {
  switch (resolution.resolution_type) {
    case 'refund':
      return 'Refund'
    case 'compensation':
      return 'Compensation'
    case 'discount':
      return resolution.discount_percentage ? `${Number(resolution.discount_percentage)}% discount` : 'Discount'
    case 'no_action':
      return 'Closed without a payout'
  }
}

/** Where a claim's refund stands, in words for the customer. `refund_request.status` has more values than one person needs. */
export function customerRefundLabel(status: string): string {
  switch (status) {
    case 'pending_review':
    case 'accounts_reviewed':
    case 'pending_approval':
      return 'Being reviewed'
    case 'approved':
      return 'Approved: the payout is being arranged'
    case 'processed':
      return 'Paid'
    case 'applied_as_credit':
      return 'Applied as credit to your account'
    case 'rejected':
      return 'Not approved'
    default:
      return 'Being reviewed'
  }
}

