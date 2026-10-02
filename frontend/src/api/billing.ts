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
import type { PresignedResponse } from '../hooks/useFileUpload'

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
  /** Always a USD-equivalent figure, whatever currency the tenant actually
   *  priced this invoice in (cbm_rate_currency) — see cbm_breakdown for the
   *  real per-package-type detail in that currency. */
  cbm_rate_usd: string
  /** 'USD' | 'NGN' — the tenant's configured CBM currency at billing time. */
  cbm_rate_currency?: string
  /** 'flat' | 'per_package_type' — whether the tenant priced this invoice
   *  with one rate or separate carton/bag/bale rates. */
  cbm_rate_mode?: string
  /** Per-package-type CBM/rate/subtotal, in cbm_rate_currency — always
   *  present, but only worth rendering as a breakdown when cbm_rate_mode
   *  is 'per_package_type' (flat invoices show the single rate line as
   *  before). Becomes historical record only if a CBM dispute later
   *  adjusts total_cbm (disputes are whole-invoice, never per-type). */
  cbm_breakdown?: Record<'carton' | 'bag' | 'bale', { cbm: string; rate: string; subtotal: string }> | null
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

export type PaymentClaimStatus = 'pending' | 'confirmed' | 'rejected'

/**
 * A customer's "I've made this payment" submission for a manual bank
 * transfer — evidence is mandatory (services/payment_release/models.py's
 * SubmitPaymentClaimRequest rejects a request without it), so a claim can
 * never reach staff without proof attached.
 */
export interface PaymentClaim {
  id: string
  tenant_id: string
  billing_id: string
  customer_id: string
  amount_ngn: string
  evidence_file_key: string
  evidence_file_name: string
  customer_note: string | null
  status: PaymentClaimStatus
  rejection_reason: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  payment_record_id: string | null
  submitted_at: string
}

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

export interface BillingListParams {
  /** Comma-separated for multi-select (Filters panel) — a single value is fine too. */
  status?: PaymentStatus | string
  customer_id?: string
  q?: string
  /** ISO date (YYYY-MM-DD) — filters on `billed_at`, inclusive. */
  created_after?: string
  created_before?: string
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
/** Period report aggregates from GET /v1/billing/report (SQL-computed). Money
 *  fields are strings (Decimal-safe); the page parses them with Number(). */
export interface TenantReport {
  overview: {
    total_revenue_ngn: string
    total_cbm: string
    revenue_paid: string
    revenue_partially_paid: string
    revenue_unpaid: string
    revenue_released_with_outstanding: string
    revenue_waived: string
    containers_processed: number
    active_customers: number
  }
  claims: { total: number; open: number; resolved: number }
  container_pipeline: Array<{ week: string; cn: number; transit: number; arrived: number; released: number }>
  top_customers: Array<{ name: string; amount: string }>
  container_billing: Array<{
    container_number: string
    customers: number
    cbm: string
    billed: string
    collected: string
    outstanding: string
    cbm_rate_usd: string
    dollar_rate: string
  }>
}

/** Tenant-wide billing aggregates from GET /v1/billing/stats (SQL-computed). */
export interface BillingStats {
  outstanding_ngn: string
  paid_this_month_ngn: string
  overdue: number
  total: number
  unpaid: number
  partially_paid: number
  paid: number
  overpaid: number
  waived: number
  released_with_outstanding: number
}

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

  /** Tenant-wide aggregates for the list stats row + status chips — staff only,
   *  SQL-computed so it stays correct as billing grows past a single page. */
  stats: () => apiRequest<BillingStats>({ method: 'GET', path: '/v1/billing/stats' }),

  /** Period report aggregates for the TenantReports page — tenant-admin only,
   *  SQL-computed (revenue, CBM, by-status, top customers, per-container). */
  report: (params: { created_after?: string; created_before?: string } = {}) =>
    apiRequest<TenantReport>({
      method: 'GET',
      path: '/v1/billing/report',
      query: params as Record<string, string | undefined>,
    }),

  /** Recent payments across all billings — staff only (§6.1 dashboard, P2-5). */
  recentPayments: (limit = 8) =>
    apiRequest<RecentPayment[]>({ method: 'GET', path: '/v1/billing/payments', query: { limit } }),

  /**
   * B12 — customer Paystack checkout. Returns the hosted-checkout URL to
   * redirect to; the payment itself is recorded by the HMAC-verified gateway
   * webhook (POST /v1/webhooks/payment) — but see verifyPayment below for
   * why that alone isn't enough.
   */
  initializePayment: (billingId: string, callbackUrl: string) =>
    apiRequest<{ authorization_url: string; reference: string; access_code: string; amount_ngn: string }>({
      method: 'POST',
      path: `/v1/payments/${billingId}/initialize`,
      body: { callback_url: callbackUrl },
    }),

  /**
   * Ground-truth gap found live: the webhook above is the *primary* source
   * of truth, but Paystack's servers can never reach a local dev URL at
   * all, and even in production a webhook can be delayed or lost — a
   * customer would see Paystack's own "successful" page, click "View
   * invoice", and find the bill still unpaid with "Pay" still live. Called
   * from PaymentSuccess.tsx with the `reference` Paystack appends to the
   * callback URL — reconciles the payment directly against Paystack's own
   * API instead of only ever trusting the redirect or waiting on a webhook.
   * Safe to call more than once (e.g. a refreshed success page): the
   * backend shares the exact same idempotent confirmation path the webhook
   * uses.
   */
  verifyPayment: (billingId: string, reference: string) =>
    apiRequest<{
      gateway_status: string
      new_payment_status?: string
      outstanding_ngn?: string
      release_note_available?: boolean
    }>({
      method: 'POST',
      path: `/v1/payments/${billingId}/verify`,
      body: { reference },
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

/**
 * Manual bank-transfer payment claims — the customer's "I've made this
 * payment" submission with mandatory evidence, reviewed by staff. See
 * services/payment_release/service.py's payment-claim functions.
 */
export const paymentClaimApi = {
  /** Presigned S3 POST for the evidence file — upload directly, then submit() with the returned file_key. */
  getUploadUrl: (billingId: string, filename: string, contentType: string) =>
    apiRequest<PresignedResponse>({
      method: 'POST',
      path: '/v1/payments/claims/presigned-url',
      body: { billing_id: billingId, filename, content_type: contentType },
    }),

  submit: (
    billingId: string,
    body: { amount_ngn: number; evidence_file_key: string; evidence_file_name: string; customer_note?: string },
    idempotencyKey: string,
  ) => apiRequest<PaymentClaim>({ method: 'POST', path: `/v1/payments/${billingId}/claims`, body, idempotencyKey }),

  listForBilling: (billingId: string) =>
    apiRequest<PaymentClaim[]>({ method: 'GET', path: `/v1/payments/${billingId}/claims` }),

  confirm: (claimId: string) =>
    apiRequest<PaymentClaim>({ method: 'PATCH', path: `/v1/payments/claims/${claimId}/confirm` }),

  reject: (claimId: string, reason: string) =>
    apiRequest<PaymentClaim>({ method: 'PATCH', path: `/v1/payments/claims/${claimId}/reject`, body: { reason } }),

  /** Presigned GET for the evidence file itself — staff need to actually see the receipt before confirming. */
  getEvidenceUrl: (claimId: string) =>
    apiRequest<{ url: string }>({ method: 'GET', path: `/v1/payments/claims/${claimId}/evidence-url` }),
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
