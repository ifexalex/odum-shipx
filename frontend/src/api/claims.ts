/**
 * API types and bindings for the Claims service.
 *
 * Wire-format notes:
 *  - _fmt_claim response is intentionally slim: id, status, cartons_affected[],
 *    upload_urls (always null from list/get), created_at. No container_id,
 *    customer_id, or description — those are stored on the DB row but not
 *    included in the formatted response shape.
 *  - Missing/seized item responses include carton_tags[], description/reason,
 *    and their own status enums (distinct from DamageClaimStatus).
 *  - All Decimal fields (refund_amount_ngn) arrive as strings.
 */

import { apiRequest, apiRequestList } from './client'

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type DamageClaimStatus =
  | 'filed'
  | 'under_inspection'
  | 'inspection_complete'
  | 'pending_resolution'
  | 'resolved'
  | 'closed'

export type InspectionMethod = 'delegate_visit' | 'customer_evidence'

export type ResolutionType = 'refund' | 'discount' | 'no_action' | 'compensation'

export type MissingItemStatus =
  | 'reported'
  | 'investigating'
  | 'found_and_shipping'
  | 'confirmed_lost'
  | 'resolved'

export type SeizedItemStatus =
  | 'seized'
  | 'recovery_in_progress'
  | 'recovered'
  | 'permanently_lost'

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

/** One evidence file recorded against a claim. `download_url` is a short-lived link, or null if one could not be made. */
export interface ClaimEvidenceFile {
  id: string
  file_name: string
  file_type: string
  file_size_bytes: number | null
  uploaded_at: string
  download_url: string | null
}

/** What was decided. Staff's notes and the approval level are not part of this (the customer reads it too). */
export interface ClaimResolution {
  resolution_type: ResolutionType
  amount_ngn: string | null
  discount_percentage: string | null
  resolved_at: string
}

/** The refund a resolution created. */
export interface ClaimRefund {
  id: string
  status: string
  amount_ngn: string | null
}

export interface Claim {
  id: string
  reference: string | null
  status: DamageClaimStatus
  container_id: string | null
  container_number: string | null
  customer_id: string | null
  customer_name: string | null
  description: string | null
  inspection_method: InspectionMethod | null
  cartons_affected: string[]
  upload_urls: null
  created_at: string
  /** On `GET /v1/claims/{id}` only (not on the list). */
  evidence?: ClaimEvidenceFile[]
  resolution?: ClaimResolution | null
  refund?: ClaimRefund | null
}

export interface MissingItem {
  id: string
  manifest_id: string
  customer_id: string
  carton_tags: string[]
  description: string
  status: MissingItemStatus
  created_at: string
}

export interface SeizedItem {
  id: string
  container_id: string
  customer_id: string | null
  carton_tags: string[]
  reason: string
  status: SeizedItemStatus
  created_at: string
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface FileDamageClaimInput {
  container_id: string
  description: string
  cartons_affected?: string[]
  customer_id?: string  // staff-only; omitted when customer files own claim
}

export interface StartInspectionInput {
  inspection_method: InspectionMethod
}

export interface ResolveClaimInput {
  resolution_type: ResolutionType
  amount_ngn?: string
  discount_percentage?: string
  reason?: string
  notes?: string
}

export interface UpdateMissingItemInput {
  status: MissingItemStatus
  notes?: string
  refund_amount_ngn?: string
}

export interface UpdateSeizedItemInput {
  recovery_status: SeizedItemStatus
  notes?: string
  refund_amount_ngn?: string
}

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

export interface ClaimListParams {
  status?: DamageClaimStatus
  /** Staff-only in effect — the backend pins customers to their own record regardless. */
  customer_id?: string
  q?: string
  /** ISO date (YYYY-MM-DD) — filters on `damage_claim.created_at`, inclusive. */
  created_after?: string
  created_before?: string
  cursor?: string
  limit?: number
  /** Column to sort by — must match shared/pagination.py's ALLOWED_SORT_FIELDS. */
  sort?: string
  direction?: 'asc' | 'desc'
}

export interface ItemListParams {
  container_id?: string
  customer_id?: string
  status?: string
  cursor?: string
  limit?: number
}

// ---------------------------------------------------------------------------
// API bindings
// ---------------------------------------------------------------------------

export interface ClaimStats {
  total: number
  open: number
  under_inspection: number
  resolved_30d: number
  filed: number
  pending_resolution: number
  resolved: number
  closed: number
}

export const claimsApi = {
  list: (params: ClaimListParams = {}) =>
    apiRequestList<Claim>({
      method: 'GET',
      path: '/v1/claims',
      query: params as Record<string, string | number | undefined>,
    }),

  /** Tenant-wide aggregates for the list stats row + status chips — staff only,
   *  SQL-computed so it stays correct as claims grow past a single page. */
  stats: () => apiRequest<ClaimStats>({ method: 'GET', path: '/v1/claims/stats' }),

  get: (id: string) =>
    apiRequest<Claim>({ method: 'GET', path: `/v1/claims/${id}` }),

  file: (body: FileDamageClaimInput, idempotencyKey: string) =>
    apiRequest<Claim>({ method: 'POST', path: '/v1/claims', body, idempotencyKey }),

  startInspection: (id: string, body: StartInspectionInput) =>
    apiRequest<Claim>({ method: 'PATCH', path: `/v1/claims/${id}/inspect`, body }),

  resolve: (id: string, body: ResolveClaimInput) =>
    apiRequest<Claim>({ method: 'PATCH', path: `/v1/claims/${id}/resolve`, body }),
}

export const missingItemsApi = {
  list: (params: ItemListParams = {}) =>
    apiRequestList<MissingItem>({
      method: 'GET',
      path: '/v1/claims/missing-items',
      query: params as Record<string, string | number | undefined>,
    }),

  get: (id: string) =>
    apiRequest<MissingItem>({ method: 'GET', path: `/v1/claims/missing-items/${id}` }),

  update: (id: string, body: UpdateMissingItemInput) =>
    apiRequest<MissingItem>({ method: 'PATCH', path: `/v1/claims/missing-items/${id}`, body }),
}

export const seizedItemsApi = {
  list: (params: ItemListParams = {}) =>
    apiRequestList<SeizedItem>({
      method: 'GET',
      path: '/v1/claims/seized-items',
      query: params as Record<string, string | number | undefined>,
    }),

  get: (id: string) =>
    apiRequest<SeizedItem>({ method: 'GET', path: `/v1/claims/seized-items/${id}` }),

  update: (id: string, body: UpdateSeizedItemInput) =>
    apiRequest<SeizedItem>({ method: 'PATCH', path: `/v1/claims/seized-items/${id}`, body }),
}

export interface PresignedUploadResponse {
  upload_url: string
  upload_method?: string
  upload_headers?: Record<string, string>
  evidence_id: string | null
  file_key: string
}

export const presignedUploadApi = {
  getUrl: (claimId: string, filename: string, contentType: string) =>
    apiRequest<PresignedUploadResponse>({
      method: 'POST',
      path: '/v1/uploads/presigned-url',
      body: { claim_id: claimId, filename, content_type: contentType },
    }),
}
