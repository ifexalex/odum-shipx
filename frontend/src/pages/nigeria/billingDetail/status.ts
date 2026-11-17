import { type Billing, type CBMDispute } from '../../../api/billing'
import { type BadgeVariant } from '../../../design/components'
import { formatDate } from '../../../lib/format'

// ---------------------------------------------------------------------------
// Status helpers (shared across this file)
// ---------------------------------------------------------------------------

export type PaymentStatus = Billing['payment_status']

export const STATUS_VARIANT: Record<PaymentStatus, BadgeVariant> = {
  unpaid: 'error',
  partially_paid: 'warning',
  paid: 'success',
  overpaid: 'warning',
  waived: 'neutral',
  released_with_outstanding: 'warning',
  cancelled: 'neutral',
}

export function statusLabel(status: PaymentStatus): string {
  switch (status) {
    case 'unpaid':
      return 'Unpaid'
    case 'partially_paid':
      return 'Partially paid'
    case 'paid':
      return 'Paid'
    case 'overpaid':
      return 'Overpaid'
    case 'waived':
      return 'Waived'
    case 'released_with_outstanding':
      return 'Released (outstanding)'
    case 'cancelled':
      return 'Cancelled'
  }
}

export function disputeStatusLabel(status: CBMDispute['status']): string {
  switch (status) {
    case 'submitted':
      return 'Submitted'
    case 'acknowledged':
      return 'Acknowledged'
    case 'investigating':
      return 'Investigating'
    case 'escalated_china':
      return 'Escalated to China'
    case 'resolved_adjusted':
      return 'Resolved — adjusted'
    case 'resolved_no_change':
      return 'Resolved — no change'
    case 'closed':
      return 'Closed'
  }
}

export function disputeVariant(status: CBMDispute['status']): BadgeVariant {
  if (status === 'resolved_adjusted' || status === 'resolved_no_change' || status === 'closed')
    return 'success'
  if (status === 'escalated_china') return 'error'
  return 'warning'
}

export function fmtDate(d: Date): string {
  return formatDate(d, 'short')
}
