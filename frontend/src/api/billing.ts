/**
 * API types and bindings for the Billing service.
 *
 * Wire-format notes:
 *  - DB Decimal columns (total_cbm, cbm_rate_usd, dollar_rate, subtotal_usd,
 *    subtotal_ngn, total_due_ngn, total_paid_ngn, outstanding_ngn,
 *    adjustments_ngn, payments[].amount_ngn) → always JSON string.
 *  - misc_fees_ngn / carryover_ngn / storage_fees_ngn are computed with
 *    Python's sum() which returns int 0 for empty iterables, so they come
 *    back as JSON number 0 when empty, or JSON string for non-zero values.
 *    Type as string | number and coerce with Number() before display.
 *  - released_with_outstanding → JSON boolean.
 *  - _active_disputes array is embedded on the billing response by
 *    _enrich_billing() — no separate fetch needed for dispute status display.
 */

import { apiDownloadFile, apiRequest, apiRequestList, type ExportFormat } from './client'

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type PaymentStatus =
  | 'unpaid'
  | 'partially_paid'
  | 'paid'
  | 'overpaid'
  | 'waived'
  | 'released_with_outstanding'
  | 'cancelled'

export type CBMDisputeStatus =
  | 'submitted'
  | 'acknowledged'
  | 'investigating'
  | 'escalated_china'
  | 'resolved_adjusted'
  | 'resolved_no_change'
  | 'closed'

export type CarryoverStatus = 'outstanding' | 'applied' | 'exempted' | 'expired'

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

export interface MiscFee {
  description: string
  amount_ngn: string
}

export interface PaymentRecord {
  id: string
  amount_ngn: string
  payment_method: string | null
  payment_reference: string | null
  confirmed_at: string
}

export interface CarryoverRecord {
  id: string
  amount_ngn: string
  source_billing_id: string
  created_at: string
}

export interface CBMDispute {
  id: string
  billing_id: string
  original_cbm: string | null
  corrected_cbm: string | null
  status: CBMDisputeStatus
  submitted_at: string
  acknowledged_at?: string | null
  /** 24h after submitted_at — SLA for first acknowledgement. */
  acknowledge_due_by?: string | null
  /** 5 days after acknowledged_at — SLA for investigation completion. */
  investigate_due_by?: string | null
  /** 7 days after acknowledged_at — SLA for full resolution. */
  resolve_due_by?: string | null
  /** updated_at proxy when status transitioned to escalated/escalated_china. */
  auto_escalated_at?: string | null
}

export interface Billing {
  id: string
  invoice_number?: string | null
  customer_id?: string | null
  customer_name?: string | null
  container_id: string
  container_number: string | null
  total_cbm: string
  cbm_rate_usd: string
  dollar_rate: string
  subtotal_usd: string
  subtotal_ngn: string
  misc_fees: MiscFee[]
  misc_fees_ngn: string | number
  adjustments_ngn: string
  carryover_ngn: string | number
  storage_fees_ngn: string | number
  total_due_ngn: string
  total_paid_ngn: string
  outstanding_ngn: string
  payment_status: PaymentStatus
  released_with_outstanding: boolean
  billed_at: string | null
  // Set once a release note is issued for this billing's container — used to
  // compute the 14-day storage-fee grace-period countdown.
  release_note_issued_at?: string | null
  payments: PaymentRecord[]
  carryovers: CarryoverRecord[]
  _active_disputes: CBMDispute[]
}

export interface Carryover {
  id: string
  customer_id: string
  customer_name: string | null
  source_billing_id: string
  source_container_number: string | null
  target_billing_id: string | null
  amount_ngn: string
  status: CarryoverStatus
  created_at: string
}

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

export interface BillingListParams {
  status?: PaymentStatus
  customer_id?: string
  q?: string
  cursor?: string
  limit?: number
  /** Column to sort by — must match shared/pagination.py's ALLOWED_SORT_FIELDS. */
  sort?: string
  direction?: 'asc' | 'desc'
}

export interface DisputeListParams {
  status?: CBMDisputeStatus
  customer_id?: string
  cursor?: string
  limit?: number
}

export interface CarryoverListParams {
  status?: CarryoverStatus
  customer_id?: string
  cursor?: string
  limit?: number
}

/** GET /v1/billing/payments row — §6.1 recent-payments dashboard feed (P2-5). */
export interface RecentPayment {
  id: string
  billing_id: string
  customer_name: string | null
  amount_ngn: string
  // Nullable at the DB level (migration 008 dropped NOT NULL specifically to
  // support RecordPaymentInput.payment_method being optional) — this was
  // typed as a plain `string`, hiding a real crash from tsc: Dashboard.tsx
  // called `.replace()` on it directly and threw on any payment recorded
  // without a method.
  payment_method: string | null
  reference_number: string | null
  payment_date: string | null
  created_at: string
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface RecordPaymentInput {
  amount_ngn: string
  payment_method?: string
  payment_reference?: string
}

export interface ResolveCBMDisputeInput {
  status: 'resolved_adjusted' | 'resolved_no_change'
  corrected_cbm?: string
  resolution_notes: string
}

// ---------------------------------------------------------------------------
// API bindings
// ---------------------------------------------------------------------------

export const billingApi = {
  list: (params: BillingListParams = {}) =>
    apiRequestList<Billing>({
      method: 'GET',
      path: '/v1/billing',
      query: params as Record<string, string | number | undefined>,
    }),

  listForCustomer: (customerId: string) =>
    apiRequest<Billing[]>({ method: 'GET', path: `/v1/billing/${customerId}` }),

  /** Recent payments across all billings — staff only (§6.1 dashboard, P2-5). */
  recentPayments: (limit = 8) =>
    apiRequest<RecentPayment[]>({ method: 'GET', path: '/v1/billing/payments', query: { limit } }),

  /**
   * B12 — customer Paystack checkout. Returns the hosted-checkout URL to
   * redirect to; the payment itself is recorded by the HMAC-verified gateway
   * webhook (POST /v1/webhooks/payment), never by the redirect.
   */
  initializePayment: (billingId: string, callbackUrl: string) =>
    apiRequest<{ authorization_url: string; reference: string; access_code: string; amount_ngn: string }>({
      method: 'POST',
      path: `/v1/payments/${billingId}/initialize`,
      body: { callback_url: callbackUrl },
    }),

  recordPayment: (billingId: string, body: RecordPaymentInput, idempotencyKey: string) =>
    apiRequest<{ new_payment_status: string; amount_ngn: string }>({
      method: 'POST',
      path: `/v1/payments/${billingId}/confirm`,
      body,
      idempotencyKey,
    }),

  cancel: (billingId: string, body: { cancel_reason: string }) =>
    apiRequest<Billing>({ method: 'PATCH', path: `/v1/billing/${billingId}/cancel`, body }),

  applyCarryover: (billingId: string, carryoverId: string) =>
    apiRequest<{ billing_id: string; carryover_id: string; new_total_ngn: string; new_balance_ngn: string }>({
      method: 'PATCH',
      path: `/v1/billing/${billingId}/apply-carryover`,
      body: { carryover_id: carryoverId },
    }),

  /**
   * Export a single billing record — xlsx/csv for staff analysis, or pdf for
   * a printable invoice. `GET /v1/billing/{id}/export` allows the customer
   * role too (own record only, enforced server-side), so this doubles as
   * the customer-facing "Download invoice" action.
   */
  export: (id: string, format: ExportFormat) =>
    apiDownloadFile(`/v1/billing/${id}/export`, format, `billing-${id}.${format}`),

  /** xlsx or csv export for all billing records in a container. */
  exportByContainer: (containerId: string, format: Exclude<ExportFormat, 'pdf'>) =>
    apiDownloadFile(`/v1/containers/${containerId}/billing/export`, format, `billing-container-${containerId}.${format}`),

  listStorageFees: (billingId: string) =>
    apiRequest<StorageFeeEntry[]>({ method: 'GET', path: `/v1/billing/${billingId}/storage-fees` }),

  /** Full misc-charge rows (with ids) — richer than the embedded misc_fees display list. */
  listMiscCharges: (billingId: string) =>
    apiRequest<MiscCharge[]>({ method: 'GET', path: `/v1/billing/${billingId}/charges` }),

  addMiscCharge: (billingId: string, body: AddMiscChargeInput) =>
    apiRequest<MiscCharge>({ method: 'POST', path: `/v1/billing/${billingId}/charges`, body }),

  /** tenant_admin only; billing must still be unpaid. */
  deleteMiscCharge: (billingId: string, chargeId: string) =>
    apiRequest<undefined>({ method: 'DELETE', path: `/v1/billing/${billingId}/charges/${chargeId}` }),

  waiveStorageFees: (billingId: string, reason: string) =>
    apiRequest<Billing>({ method: 'POST', path: `/v1/billing/${billingId}/storage-fees/waive`, body: { reason } }),
}

export interface StorageFeeEntry {
  id: string
  day_number: number
  carton_count: number
  daily_rate_ngn: string
  fee_amount_ngn: string
  accrual_date: string
}

export interface MiscCharge {
  id: string
  billing_id: string
  charge_type: string
  description: string
  amount_usd: string | null
  amount_ngn: string
  created_at: string
}

export interface AddMiscChargeInput {
  description: string
  amount_ngn: string
  charge_type?: string
  /** Configured charge_type row this charge came from — attributes it for usage counts (§4.4). */
  charge_type_id?: string
  amount_usd?: string
}

export interface FileDisputeInput {
  disputed_cbm: string
  reason: string
}

export const disputeApi = {
  list: (params: DisputeListParams = {}) =>
    apiRequestList<CBMDispute>({
      method: 'GET',
      path: '/v1/billing/disputes',
      query: params as Record<string, string | number | undefined>,
    }),

  file: (billingId: string, body: FileDisputeInput) =>
    apiRequest<CBMDispute>({
      method: 'POST',
      path: `/v1/billing/${billingId}/dispute`,
      body,
    }),

  acknowledge: (disputeId: string) =>
    apiRequest<CBMDispute>({
      method: 'PATCH',
      path: `/v1/billing/disputes/${disputeId}/acknowledge`,
      body: {},
    }),

  resolve: (disputeId: string, body: ResolveCBMDisputeInput) =>
    apiRequest<CBMDispute>({ method: 'PATCH', path: `/v1/billing/disputes/${disputeId}/resolve`, body }),

  reject: (disputeId: string, reason: string) =>
    apiRequest<CBMDispute>({
      method: 'PATCH',
      path: `/v1/billing/disputes/${disputeId}/reject`,
      body: { reason },
    }),
}

export const carryoverApi = {
  list: (params: CarryoverListParams = {}) =>
    apiRequestList<Carryover>({
      method: 'GET',
      path: '/v1/billing/carryovers',
      query: params as Record<string, string | number | undefined>,
    }),

  exempt: (carryoverId: string, notes?: string) =>
    apiRequest<Carryover>({
      method: 'PATCH',
      path: `/v1/billing/carryovers/${carryoverId}/exempt`,
      body: { notes },
    }),
}
