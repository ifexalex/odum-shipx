import { apiRequest } from './client'

// Ground truth: services/excel/{service,import_packing_list}.py.
// POST /v1/packing-lists/import is a single combined parse+commit call —
// there is no separate dry-run/validate-only endpoint. Every invalid row is
// unconditionally skipped and reported in `error_details`; there is no
// severity distinction (warning vs blocking) and no "skip invalid rows"
// toggle in the backend — skipping is the only behavior. See
// 07_domain_modules.md's 7.2 notes for the full investigation.
export interface ImportErrorDetail {
  row: number
  field: string
  value: string
  error: string
  /** Manifest imports only — real exports split layouts across several sheets. */
  sheet?: string
}

export interface ImportResult {
  total_rows: number
  imported: number
  errors: number
  packing_lists_created: number
  error_details: ImportErrorDetail[]
}

// Ground truth: services/excel/{service,import_manifest}.py.
// POST /v1/manifests/import takes a forwarder's own manifest export rather
// than a ShipX template: the container is read from the file's "PARTIAL NO"
// header (not chosen by the user), and containers/customers/packing lists are
// created on the fly when they don't already exist. Re-importing the same file
// is idempotent — matched rows come back in `items_skipped_duplicate`, not as
// errors. See 19_excel_import_export.md §"Manifest Import".
export interface ManifestImportResult {
  total_rows: number
  imported: number
  errors: number
  containers_created: number
  customers_created: number
  packing_lists_created: number
  items_created: number
  items_skipped_duplicate: number
  error_details: ImportErrorDetail[]
}

// Backed by services/excel/service.py's generate_import_presigned_url() —
// an S3 POST-policy upload scoped to {tenant_id}/imports/{uuid}.xlsx, added
// specifically to unblock this wizard (no generic upload endpoint existed
// before). Cloud-neutral PUT contract: the file is the raw request body and
// `upload_headers` (Content-Type) are sent as request headers.
export interface ImportPresignedUrlResponse {
  upload_url: string
  upload_method?: string
  upload_headers?: Record<string, string>
  file_key: string
}

export const XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

export const excelApi = {
  getImportPresignedUrl: (contentType: string) =>
    apiRequest<ImportPresignedUrlResponse>({
      method: 'POST',
      path: '/v1/packing-lists/import/presigned-url',
      body: { content_type: contentType },
    }),

  importPackingList: (containerId: string, fileKey: string) =>
    apiRequest<ImportResult>({
      method: 'POST',
      path: '/v1/packing-lists/import',
      body: { container_id: containerId, file_key: fileKey },
    }),

  // No container_id: the manifest carries its own "PARTIAL NO" header, and the
  // backend finds-or-creates the container from it.
  importManifest: (fileKey: string) =>
    apiRequest<ManifestImportResult>({
      method: 'POST',
      path: '/v1/manifests/import',
      body: { file_key: fileKey },
    }),
}
