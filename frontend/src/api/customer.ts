/**
 * Customer-facing API bindings.
 *
 * Covers:
 *  - Public shipment tracking (no auth — /v1/shipments/:code?phone=...)
 *  - Customer self-profile (read from session; no dedicated GET /v1/customers/me endpoint exists)
 *
 * Customer billing, release-notes, claims, and refunds use the same shared
 * API modules (billing.ts, releaseNotes.ts, claims.ts, refunds.ts) — those
 * endpoints auto-scope to the authenticated customer's own records.
 *
 * Security note: never log or debug-print account_number, account_name,
 * delegate_id_number, or any PII fields in this module.
 */

import { apiRequest } from './client'

// ---------------------------------------------------------------------------
// Public tracking (no JWT required)
// ---------------------------------------------------------------------------

export interface TrackingStageEvent {
  stage: string
  occurred_at: string
  notes: string | null
}

export interface PublicTrackingResult {
  tracking_code: string
  current_stage: string
  company_name: string | null
  stage_history: TrackingStageEvent[]
  estimated_stages: null
}

export const publicTrackingApi = {
  /**
   * Requires tracking_code + phone for ownership verification.
   * No Authorization header sent — backend accepts without JWT.
   */
  // Ground-truth fix (2026-07-12): this hit /v1/track/{code}, which has no
  // backend route (API Gateway + local_server only serve
  // GET /v1/shipments/{code}?phone=) — every public lookup 404'd.
  lookup: (trackingCode: string, phone: string) =>
    apiRequest<PublicTrackingResult>({
      method: 'GET',
      path: `/v1/shipments/${encodeURIComponent(trackingCode)}`,
      query: { phone },
    }),
}

// ---------------------------------------------------------------------------
// Stage labels — matches services/tracking/service.py's _STATUS_TO_STAGE
// ---------------------------------------------------------------------------

const STAGE_LABELS: Record<string, string> = {
  packing: 'Being packed',
  in_transit: 'In transit',
  arrived: 'Arrived in Nigeria',
  customs: 'Customs clearance',
  warehouse: 'At warehouse',
  released: 'Released for pickup',
  picked_up: 'Picked up',
}

export function stageLabelFor(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, ' ')
}

// ---------------------------------------------------------------------------
// Customer self-registration (no JWT — POST /v1/register)
// ---------------------------------------------------------------------------

export interface SelfRegisterInput {
  name: string
  email: string
  phone: string
  whatsapp?: string
  /** Channels the customer consents to be notified on: 'sms' | 'whatsapp' | 'email'. */
  notification_consent?: string[]
}

export interface SelfRegisterResult {
  id: string
  name: string | null
  email: string | null
}

export const registerApi = {
  /**
   * Registers a new customer against the tenant identified by `slug`
   * (POST /v1/register/{slug}). The backend provisions the Cognito user,
   * which emails a temporary password — the customer then signs in and is
   * prompted to set a permanent one (NEW_PASSWORD_REQUIRED challenge).
   */
  selfRegister: (slug: string, body: SelfRegisterInput) =>
    apiRequest<SelfRegisterResult>({ method: 'POST', path: `/v1/register/${encodeURIComponent(slug)}`, body }),
}

// ---------------------------------------------------------------------------
// Customer account-creation invites (no JWT — public claim page)
// ---------------------------------------------------------------------------

export interface InviteDetail {
  company_name: string | null
  customer_name: string | null
  expires_at: string
}

export interface AcceptInviteInput {
  email: string
  password: string
}

export interface AcceptInviteResult {
  id: string
  name: string | null
  email: string | null
  user_id: string | null
}

export const inviteApi = {
  /** GET /v1/invites/{token} — company + customer name + expiry only, no other PII. */
  get: (token: string) =>
    apiRequest<InviteDetail>({ method: 'GET', path: `/v1/invites/${encodeURIComponent(token)}` }),

  /** POST /v1/invites/{token}/accept — claims the invite, creating the customer's login. */
  accept: (token: string, body: AcceptInviteInput) =>
    apiRequest<AcceptInviteResult>({
      method: 'POST',
      path: `/v1/invites/${encodeURIComponent(token)}/accept`,
      body,
    }),
}
