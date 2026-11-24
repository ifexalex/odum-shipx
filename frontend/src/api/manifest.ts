import { apiDownloadFile, apiRequest, apiRequestList, type ExportFormat } from './client'

// Ground truth: services/manifest/{service,repository,models}.py. Manifests
// are auto-created when a packing list is approved (Task 08) — there is no
// POST route here. Real responses are built by spreading the raw repository
// row (get_manifest/verify_manifest/resolve_discrepancy), not the
// (unused-for-output) ManifestResponse Pydantic model — that's why
// weight_discrepancies appears on GET/verify responses despite not being in
// models.py's ManifestResponse, and why resolve_discrepancy's response omits
// it (only get_manifest/verify_manifest compute it).
//
// total_cbm/total_weight_kg (here and on ManifestCustomerSummary) are
// DECIMAL columns — strings on the wire, same caveat as packingList.ts's
// PackingList.total_cbm (see decimal.ts). weight_discrepancies' numeric
// fields are the one exception: service.py casts them through float()
// before returning, so those are real JSON numbers, not strings.
export type VerificationStatus = 'pending' | 'verified' | 'discrepancies_found' | 'resolved'

export interface ManifestCustomerSummary {
  customer_id: string
  customer_name: string | null
  customer_phone: string | null
  packing_list_id: string | null
  carton_count: number
  total_weight_kg: string | null
  total_cbm: string | null
  carton_tags: string[]
}

export interface WeightDiscrepancy {
  item_id: string | null
  carton_tag: string | null
  tracking_code: string | null
  customer_id: string | null
  weight_dispatch_kg: number
  weight_actual_kg: number
  difference_kg: number
}

export interface ManifestMissingItem {
  id: string
  customer_id: string
  carton_tags: string[]
  description: string | null
  status: string
}

// §6.3 verification evidence (F-D3). Photos/docs attached while logging a
// discrepancy; download_url is a short-lived presigned S3 GET.
export interface ManifestEvidence {
  id: string
  file_name: string
  file_type: string
  label: string | null
  download_url: string
  created_at: string
}

// Presigned-upload contract — mirrors claims' PresignedUploadResponse.
export interface ManifestEvidenceUploadResponse {
  upload_url: string
  upload_method?: string
  upload_headers?: Record<string, string>
  evidence_id: string | null
  file_key: string
}

export interface Manifest {
  id: string
  tenant_id: string
  container_id: string
  container_number: string | null
  container_status: string | null
  total_customers: number
  total_cartons: number
  total_weight_kg: string
  total_cbm: string
  /** Package breakdown by unit for the container, summing each item's quantity:
   *  e.g. { carton: 120, bale: 8, bag: 30 }. Null/absent when the manifest has
   *  no approved packing-list items yet. See PACKAGE_UNIT_ORDER/ABBR below. */
  package_mix?: Record<string, number> | null
  verification_status: VerificationStatus
  verified_by: string | null
  verified_at: string | null
  notes: string | null
  customers: ManifestCustomerSummary[]
  // Present on GET /{id} and PATCH /verify; absent on PATCH /resolve-discrepancy.
  weight_discrepancies?: WeightDiscrepancy[]
  // Present on GET /{id} when verification_status is discrepancies_found or resolved.
  missing_items?: ManifestMissingItem[]
  // Present on GET /{id} — verification photos/docs (F-D3).
  evidence?: ManifestEvidence[]
  created_at: string
  updated_at: string
}

// Canonical display order + short labels for the package-mix breakdown.
export const PACKAGE_UNIT_ORDER = ['carton', 'bale', 'bag', 'sack', 'pallet', 'unspecified'] as const
export const PACKAGE_UNIT_ABBR: Record<string, string> = {
  carton: 'ctn',
  bale: 'bale',
  bag: 'bag',
  sack: 'sack',
  pallet: 'plt',
  unspecified: 'pkg',
}

/** Ordered, non-zero entries of a package_mix map for display. Unknown units
 *  (shouldn't occur) sort last but are still shown with their raw label. */
export function orderedPackageMix(
  mix: Record<string, number> | null | undefined,
): { unit: string; abbr: string; qty: number }[] {
  if (!mix) return []
  const known = PACKAGE_UNIT_ORDER as readonly string[]
  return Object.entries(mix)
    .filter(([, qty]) => qty > 0)
    .sort(([a], [b]) => {
      const ia = known.indexOf(a), ib = known.indexOf(b)
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    })
    .map(([unit, qty]) => ({ unit, abbr: PACKAGE_UNIT_ABBR[unit] ?? unit, qty }))
}

export interface DiscrepancyInput {
  customer_id: string
  carton_tags: string[]
  type: 'missing' | 'damaged'
  notes?: string
}

export interface VerifyManifestInput {
  verification_status: 'verified' | 'discrepancies_found'
  discrepancies?: DiscrepancyInput[]
}

export interface ResolveDiscrepancyInput {
  resolution_notes: string
}

export interface ManifestListParams {
  cursor?: string
  limit?: number
  verification_status?: VerificationStatus
  container_id?: string
}

export const manifestApi = {
  list: (params: ManifestListParams = {}) =>
    apiRequestList<Manifest>({
      method: 'GET',
      path: '/v1/manifests',
      query: params as Record<string, string | number | undefined>,
    }),

  get: (id: string) => apiRequest<Manifest>({ method: 'GET', path: `/v1/manifests/${id}` }),

  /** Per-verification-status counts + B11 overdue for the §6.2 stats row (P2-4). */
  stats: () =>
    apiRequest<{ pending: number; verified: number; discrepancies_found: number; resolved: number; overdue: number }>({
      method: 'GET',
      path: '/v1/manifests/stats',
    }),

  verify: (id: string, body: VerifyManifestInput) =>
    apiRequest<Manifest>({ method: 'PATCH', path: `/v1/manifests/${id}/verify`, body }),

  resolveDiscrepancy: (id: string, body: ResolveDiscrepancyInput) =>
    apiRequest<Manifest>({ method: 'PATCH', path: `/v1/manifests/${id}/resolve-discrepancy`, body }),

  revokeVerification: (id: string) =>
    apiRequest<Manifest>({ method: 'PATCH', path: `/v1/manifests/${id}/revoke-verification`, body: {} }),

  // Presigned upload for a verification photo/doc (§6.3). The browser then POSTs
  // the file straight to S3 using the returned url + fields.
  getEvidenceUploadUrl: (id: string, filename: string, contentType: string, sizeBytes: number, label?: string) =>
    apiRequest<ManifestEvidenceUploadResponse>({
      method: 'POST',
      path: `/v1/manifests/${id}/evidence`,
      body: { filename, content_type: contentType, size_bytes: sizeBytes, label },
    }),

  /** After the upload: the API checks the stored size and lists the file on the manifest. */
  confirmEvidence: (id: string, evidenceId: string) =>
    apiRequest<ManifestEvidence>({ method: 'POST', path: `/v1/manifests/${id}/evidence/${evidenceId}/confirm` }),

  export: (id: string, format: Exclude<ExportFormat, 'pdf'>) =>
    apiDownloadFile(`/v1/manifests/${id}/export`, format, `manifest-${id}.${format}`),

  /** The manifest as a branded PDF (FD-39), opened in a new tab. */
  pdf: (id: string) => apiDownloadFile(`/v1/manifests/${id}/pdf`, 'pdf', `manifest-${id}.pdf`),
}
