import type { InvoiceResult } from './billing'
import { apiRequest, apiRequestList } from './client'

// Ground truth: services/tracking/{models,service,repository}.py +
// 05a_database_schema_core.md's `container` table. Vessel/voyage/shipping-line/
// seal-number/container-type were added to the schema in migration 030, so the
// China create-container form and packing-list wizard can capture them; all are
// nullable. `packing_list_count` is a derived aggregate returned on list/get.
export type ContainerStatus =
  | 'loading'
  | 'sealed'
  | 'in_transit'
  | 'arrived'
  | 'customs_clearance'
  | 'cleared'
  | 'at_warehouse'
  | 'fully_released'
  | 'cancelled'

export interface Container {
  id: string
  tenant_id: string
  container_number: string
  parcel_number: string | null
  origin: string
  destination: string
  ship_date: string | null
  estimated_arrival_date: string | null
  actual_arrival_date: string | null
  status: ContainerStatus
  notes: string | null
  // Vessel/voyage manifest details (migration 030) — all nullable.
  vessel_name: string | null
  voyage_number: string | null
  shipping_line: string | null
  seal_number: string | null
  container_type: string | null
  // Capacity preset snapshot (migration 051) — NUMERIC, returned as string.
  capacity_cbm: string | null
  recommended_cbm: string | null
  // Derived aggregates (correlated subqueries on list + get).
  packing_list_count?: number
  approved_packing_list_count?: number
  // Sum of total_cbm across all packing lists on this container (DECIMAL → string).
  total_cbm_packed?: string
  created_by: string | null
  created_by_name?: string | null
  created_at: string
  updated_at: string
}

export interface ContainerEvent {
  id: string
  from_status: string
  to_status: string
  actor_id: string
  actor_name: string | null
  actor_role: string | null
  notes: string | null
  created_at: string
}

export interface CreateContainerInput {
  container_number: string
  parcel_number?: string
  origin?: string
  destination?: string
  estimated_arrival_date?: string
  notes?: string
  vessel_name?: string
  voyage_number?: string
  shipping_line?: string
  seal_number?: string
  container_type?: string
  capacity_cbm?: number
  recommended_cbm?: number
}

/** `PATCH /v1/containers/{id}/status` response: the container, plus `billing_summary` when the new status is `cleared`. */
export type ContainerStatusUpdate = Container & { billing_summary?: InvoiceResult[] }

export interface UpdateContainerStatusInput {
  new_status: ContainerStatus
  ship_date?: string
  notes?: string
}

export interface ContainerListParams {
  cursor?: string
  limit?: number
  /** Comma-separated for the Filters panel's multi-select (e.g. "sealed,in_transit"). */
  status?: string
  q?: string
  /** ISO date (YYYY-MM-DD) — containers created on/after this date. */
  created_after?: string
  /** ISO date (YYYY-MM-DD) — containers created on/before this date. */
  created_before?: string
  /** ISO date (YYYY-MM-DD) — containers whose ETA is on/after this date. */
  eta_after?: string
  /** ISO date (YYYY-MM-DD) — containers whose ETA is on/before this date. */
  eta_before?: string
  /** Column to sort by — must match shared/pagination.py's ALLOWED_SORT_FIELDS. */
  sort?: string
  direction?: 'asc' | 'desc'
}

export interface ContainerStats {
  total: number
  loading: number
  sealed: number
  in_transit: number
  arrived: number
  customs_clearance: number
  cleared: number
  at_warehouse: number
  fully_released: number
  cancelled: number
  cleared_30d: number
}

export const containersApi = {
  list: (params: ContainerListParams = {}) =>
    apiRequestList<Container>({
      method: 'GET',
      path: '/v1/containers',
      query: params as Record<string, string | number | undefined>,
    }),

  /** Tenant-wide per-status counts for the list stats row + chips — staff only,
   *  SQL-computed so it stays correct as containers grow past a single page. */
  stats: () => apiRequest<ContainerStats>({ method: 'GET', path: '/v1/containers/stats' }),

  get: (id: string) => apiRequest<Container>({ method: 'GET', path: `/v1/containers/${id}` }),

  create: (body: CreateContainerInput, idempotencyKey: string) =>
    apiRequest<Container>({ method: 'POST', path: '/v1/containers', body, idempotencyKey }),

  updateStatus: (id: string, body: UpdateContainerStatusInput) =>
    apiRequest<ContainerStatusUpdate>({ method: 'PATCH', path: `/v1/containers/${id}/status`, body }),

  events: (id: string) => apiRequest<ContainerEvent[]>({ method: 'GET', path: `/v1/containers/${id}/events` }),
  delete: (id: string) => apiRequest<{ deleted: boolean }>({ method: 'DELETE', path: `/v1/containers/${id}` }),
  cancel: (id: string, notes?: string) =>
    apiRequest<Container>({ method: 'POST', path: `/v1/containers/${id}/cancel`, body: { notes } }),
}

// ---------------------------------------------------------------------------
// Container documents (Section 5.3 Documents tab)
// Upload flow: POST presigned-url → S3 presigned-POST form upload → done
// (the backend registers the document row when issuing the presigned URL).
// ---------------------------------------------------------------------------

export type ContainerDocumentType =
  | 'bill_of_lading'
  | 'customs_certificate'
  | 'insurance'
  | 'inspection_report'
  | 'other'

export interface ContainerDocument {
  id: string
  container_id: string
  document_type: ContainerDocumentType
  filename: string
  content_type: string
  uploaded_by: string | null
  created_at: string
}

export interface DocumentPresignedUpload {
  upload_url: string
  upload_method?: string
  upload_headers?: Record<string, string>
  document_id: string | null
  s3_key: string
  expires_in_seconds: number
}

export const containerDocumentsApi = {
  list: (containerId: string) =>
    apiRequest<ContainerDocument[]>({ method: 'GET', path: `/v1/containers/${containerId}/documents` }),

  presignUpload: (containerId: string, body: { filename: string; content_type: string; document_type: ContainerDocumentType }) =>
    apiRequest<DocumentPresignedUpload>({
      method: 'POST',
      path: `/v1/containers/${containerId}/documents/presigned-url`,
      body,
    }),

  /** Short-lived (5 min) GET URL with attachment disposition. */
  downloadUrl: (containerId: string, docId: string) =>
    apiRequest<{ download_url: string }>({
      method: 'GET',
      path: `/v1/containers/${containerId}/documents/${docId}/download`,
    }),
}

/** Uploads the file directly to storage via the presigned PUT URL (no auth header). */
export async function uploadToPresignedUrl(presigned: DocumentPresignedUpload, file: File): Promise<void> {
  const res = await fetch(presigned.upload_url, {
    method: presigned.upload_method ?? 'PUT',
    headers: presigned.upload_headers ?? { 'Content-Type': file.type },
    body: file,
  })
  if (!res.ok) throw new Error(`Upload failed (${res.status})`)
}
