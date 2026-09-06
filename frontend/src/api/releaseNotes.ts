/**
 * API types and bindings for the Payment Release service (release notes + pickup).
 *
 * Wire-format notes:
 *  - authorized_at is an ISO datetime string.
 *  - carton_count / total_cartons_for_customer are plain JSON numbers (not Decimal).
 *  - warehouse_address is always null in the current backend response.
 *  - pickup response returns remaining_cartons (int) and optional shipment_status.
 */

import { apiDownloadFile, apiRequest, apiRequestList } from './client'

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type ReleaseNoteStatus = 'active' | 'picked_up' | 'expired' | 'cancelled'

export type DelegateIdType = 'national_id' | 'drivers_license' | 'passport'

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

export interface ReleaseNote {
  id: string
  reference_number: string
  customer_name: string | null
  container_number: string | null
  carton_count: number
  total_cartons_for_customer: number
  is_partial_release: boolean
  carton_tags: string[]
  payment_status: string
  status: ReleaseNoteStatus
  authorized_at: string
  warehouse_address: string | null
  /** ISO date string (YYYY-MM-DD). Set on creation; expiry job uses it to flip status to 'expired'. Detail responses only. */
  valid_until?: string | null
  /** ISO datetime string when the note transitioned to 'expired' (proxy: updated_at). Detail responses only. */
  expired_at?: string | null
  /** ISO datetime string when the note was fully picked up (proxy: updated_at). Feeds the warehouse done-today count. */
  picked_up_at?: string | null
  /** Outstanding storage fees on the linked billing record — shown on expired UI. Detail responses only. */
  storage_fees_ngn?: string
  /** ID of the note this was reissued from (or the parent split note). Detail responses only. */
  parent_release_note_id?: string | null
}

export interface PickupResult {
  release_note_id: string
  release_note_status: ReleaseNoteStatus
  pickup_record_id: string
  pickup_date: string
  pickup_time: string | null
  attendant_name: string | null
  remaining_cartons: number
  shipment_status: string | null
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface CreateReleaseNoteInput {
  billing_id: string
  carton_tags: string[]
  release_with_outstanding?: boolean
  approval_notes?: string
}

export interface RecordPickupInput {
  cartons_released: number
  is_delegate?: boolean
  // Required by the backend when is_delegate is false (RecordPickupRequest's
  // _require_collector_name_for_non_delegate) — added here because it was
  // missing entirely, silently breaking every non-delegate pickup (the
  // customer collecting in person) with a raw validation crash.
  collected_by_name?: string
  delegate_name?: string
  delegate_phone?: string
  delegate_id_type?: DelegateIdType
  delegate_id_number?: string
  notes?: string
}

export interface SplitReleaseNoteInput {
  carton_tags: string[]
  notes?: string
}

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

export interface ReleaseNoteListParams {
  status?: ReleaseNoteStatus
  customer_id?: string
  container_id?: string
  /** Exact reference_number match — the warehouse scan-or-type lookup (P2-2). */
  reference?: string
  cursor?: string
  limit?: number
}

// ---------------------------------------------------------------------------
// API bindings
// ---------------------------------------------------------------------------

export const releaseNotesApi = {
  list: (params: ReleaseNoteListParams = {}) =>
    apiRequestList<ReleaseNote>({
      method: 'GET',
      path: '/v1/release-notes',
      query: params as Record<string, string | number | undefined>,
    }),

  get: (id: string) =>
    apiRequest<ReleaseNote>({ method: 'GET', path: `/v1/release-notes/${id}` }),

  /** Per-status counts for the §9.1 stats row (P2-3). Staff/warehouse only. */
  stats: () =>
    apiRequest<{ active: number; partial_active: number; picked_up_today: number; picked_up: number; expired: number }>({
      method: 'GET',
      path: '/v1/release-notes/stats',
    }),

  create: (body: CreateReleaseNoteInput) =>
    apiRequest<ReleaseNote>({ method: 'POST', path: '/v1/release-notes', body }),

  recordPickup: (id: string, body: RecordPickupInput) =>
    apiRequest<PickupResult>({ method: 'PATCH', path: `/v1/release-notes/${id}/release`, body }),

  split: (id: string, body: SplitReleaseNoteInput) =>
    apiRequest<ReleaseNote>({ method: 'POST', path: `/v1/release-notes/${id}/split`, body }),

  /** PDF export — opens in new browser tab (printable pickup authorisation). */
  pdf: (id: string) =>
    apiDownloadFile(`/v1/release-notes/${id}/pdf`, 'pdf', `release-note-${id}.pdf`),

  /** Re-issue an expired release note with a fresh 14-day validity window. */
  reissue: (id: string) =>
    apiRequest<ReleaseNote>({ method: 'POST', path: `/v1/release-notes/${id}/reissue`, body: {} }),
}
