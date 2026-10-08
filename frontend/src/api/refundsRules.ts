import type { UserRole } from '../auth/types'
import type { ApprovalLevel, Refund, RefundStatus } from './refunds'

// Roles that can review (accounts team step)
const _REVIEW_ROLES: UserRole[] = ['nigeria_office_staff']
// Roles that can approve or reject
const _APPROVE_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']

export const REFUND_STATUS_ORDER: RefundStatus[] = [
  'pending_review',
  'pending_approval',
  'processed',
]

export function isTerminalRefundStatus(status: RefundStatus): boolean {
  return status === 'processed' || status === 'applied_as_credit' || status === 'rejected'
}

export function canReviewRefund(refund: Refund, role: UserRole): boolean {
  return _REVIEW_ROLES.includes(role) && refund.status === 'pending_review'
}

export function canApproveRefund(refund: Refund, role: UserRole): boolean {
  if (!_APPROVE_ROLES.includes(role)) return false
  if (refund.status !== 'pending_approval') return false
  // head_of_finance level requires tenant_admin
  if (refund.approval_level === 'head_of_finance' && role !== 'tenant_admin') return false
  return true
}

export function canRejectRefund(refund: Refund, role: UserRole): boolean {
  const rejectableStatuses: RefundStatus[] = ['pending_review', 'pending_approval']
  return _APPROVE_ROLES.includes(role) && rejectableStatuses.includes(refund.status)
}

export function approvalLevelLabel(level: ApprovalLevel | null): string {
  if (level === 'head_of_finance') return 'Head of finance approval required'
  if (level === 'manager') return 'Manager approval required'
  return 'Pending approval'
}

export function refundTypeLabel(type: Refund['refund_type']): string {
  switch (type) {
    case 'overpayment': return 'Overpayment refund'
    case 'cbm_correction': return 'CBM correction'
    case 'damage_or_loss': return 'Damage / loss'
    // No default meant a missing/unmapped value returned undefined, which
    // React renders as nothing — RefundDetail.tsx's page <h1> silently went
    // blank for every claim-triggered refund, since
    // create_refund_request_for_claim never set refund_type at all (fixed
    // in services/claims/repository.py). A blank heading is a worse failure
    // mode than a generic label — it looks like the page didn't load.
    default: return 'Refund request'
  }
}

export function customerChoiceLabel(choice: Refund['customer_choice']): string {
  if (choice === 'immediate_refund') return 'Immediate bank refund'
  if (choice === 'credit_next_shipment') return 'Credit on next shipment'
  return '—'
}
