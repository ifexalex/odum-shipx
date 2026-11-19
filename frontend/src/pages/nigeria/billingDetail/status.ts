import { type Billing } from '../../../api/billing'
import { formatDate } from '../../../lib/format'

// ---------------------------------------------------------------------------
// Status helpers (shared across this file)
// ---------------------------------------------------------------------------

export type PaymentStatus = Billing['payment_status']

export function fmtDate(d: Date): string {
  return formatDate(d, 'short')
}
