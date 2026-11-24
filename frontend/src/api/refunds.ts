/**
 * API types and bindings for the Refunds service.
 *
 * Wire-format notes:
 *  - amount_requested_ngn / amount_approved_ngn arrive as JSON strings (Decimal).
 *  - State machine (actual backend flow — not the spec diagram):
 *      pending_review → pending_approval (debt_check_passed=true) | rejected
 *      pending_approval → processed | applied_as_credit | rejected
 *  - "approved" and "accounts_reviewed" exist in the DB enum but are not reached
 *    by the current service path — approve() skips straight to processed/applied_as_credit.
 *  - approval_level: "manager" (overpayment / small damage_or_loss) or
 *    "head_of_finance" (cbm_correction / large damage_or_loss). tenant_admin
 *    covers both; nigeria_office_staff is capped by refund_threshold_usd config.
 */

import { apiRequest, apiRequestList } from './client'

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type RefundStatus =
  | 'pending_review'
  | 'accounts_reviewed'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'processed'
  | 'applied_as_credit'

export type RefundType = 'overpayment' | 'cbm_correction' | 'damage_or_loss' | 'missing_item' | 'seized_item'

export type CustomerChoice = 'immediate_refund' | 'credit_next_shipment'

export type ApprovalLevel = 'manager' | 'head_of_finance'

// ---------------------------------------------------------------------------
// Response shape
// ---------------------------------------------------------------------------

/**
 * Threshold info injected by GET /v1/refunds/{id}.
 * Used to render the staff approval limit meter before the user tries to approve.
 * Only present on the detail response — not on list items.
 */
export interface RefundThreshold {
  staff_limit_usd: number
  staff_limit_ngn: number
  dollar_rate: number
  /** True when amount_requested_ngn > staff_limit_ngn. */
  exceeds_staff_limit: boolean
}

/**
 * Where a refund to a bank account is paid. PII: never log it. Staff read it whole; a customer reads the account
 * number masked (`******6789`). Null when the refund is a credit, or came from a claim decision.
 */
export interface BankDetails {
  bank_name: string | null
  account_number: string | null
  account_name: string | null
}

export interface Refund {
  id: string
  status: RefundStatus
  refund_type: RefundType
  amount_requested_ngn: string
  amount_approved_ngn: string | null
  /** For a refund taken as credit: how much of it invoices have used so far. The rest is still the customer's. */
  credit_applied_ngn?: string
  customer_choice: CustomerChoice | null
  customer_id: string | null
  billing_id: string | null
  damage_claim_id: string | null
  /** What the three ids above are called (FD-17). Sent on the detail read only; absent on list rows. */
  customer_name?: string | null
  invoice_number?: string | null
  claim_reference?: string | null
  reason: string | null
  rejection_reason: string | null
  approval_level: ApprovalLevel | null
  debt_check_passed: boolean | null
  debt_check_notes: string | null
  created_at: string
  bank_details?: BankDetails | null
  /** Present on detail responses only (absent on list items / route state). Null if threshold config is unavailable. */
  threshold?: RefundThreshold | null
}

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

export interface RefundListParams {
  status?: RefundStatus
  customer_id?: string
  cursor?: string
  limit?: number
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface CreateRefundInput {
  customer_id: string
  billing_id?: string
  damage_claim_id?: string
  refund_type: RefundType
  amount_requested_ngn: string
  customer_choice?: CustomerChoice
  notes?: string
  /** Required for `immediate_refund`, refused for a credit. `account_number` is a 10-digit NUBAN. */
  bank_name?: string
  account_number?: string
  account_name?: string
}

export interface AccountsReviewInput {
  debt_check_passed: boolean
  debt_check_notes: string
}

export interface ApproveRefundInput {
  amount_approved_ngn: string
  approval_level: string
}

// ---------------------------------------------------------------------------
// API bindings
// ---------------------------------------------------------------------------

export const refundsApi = {
  list: (params: RefundListParams = {}) =>
    apiRequestList<Refund>({
      method: 'GET',
      path: '/v1/refunds',
      query: params as Record<string, string | number | undefined>,
    }),

  get: (id: string) =>
    apiRequest<Refund>({ method: 'GET', path: `/v1/refunds/${id}` }),

  create: (body: CreateRefundInput, idempotencyKey: string) =>
    apiRequest<Refund>({ method: 'POST', path: '/v1/refunds', body, idempotencyKey }),

  review: (id: string, body: AccountsReviewInput) =>
    apiRequest<Refund>({ method: 'PATCH', path: `/v1/refunds/${id}/review`, body }),

  approve: (id: string, body: ApproveRefundInput) =>
    apiRequest<Refund>({ method: 'PATCH', path: `/v1/refunds/${id}/approve`, body }),

  reject: (id: string, reason: string) =>
    apiRequest<Refund>({ method: 'PATCH', path: `/v1/refunds/${id}/reject`, body: { reason } }),
}
