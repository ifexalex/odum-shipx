import { apiDownloadFile, apiRequest, apiRequestList, type ExportFormat } from './client'

// Ground truth: services/packing_list/{service,repository}.py. The
// PackingListResponse Pydantic model in models.py is unused for actual
// serialization — handlers return the raw repository dict via
// `_assemble_response()`, which spreads every DB column. That's why fields
// like created_by/approved_by/approval_comments below aren't in the
// documented response model but are real, present on every response, and
// load-bearing for the self-approval-hiding rule (08_api_packing_list.md).
export type PackingListStatus = 'draft' | 'pending_approval' | 'approved' | 'rejected'
export type DeliveryDateMode = 'same_day' | 'multiple_days'
export type DocumentLang = 'en' | 'zh'

// weight_dispatch_kg/weight_actual_kg/cbm/length_cm/width_cm/height_cm/declared_value_usd
// are DECIMAL columns in Postgres. shared/responses.py's json.dumps(body, default=str)
// has no native Decimal encoder, so these always serialize as strings on the wire —
// never trust `number` here, or .toFixed()/arithmetic on them will break at runtime.
export interface PackingListItem {
  id: string
  packing_list_id: string
  description: string
  weight_dispatch_kg: string | null
  weight_actual_kg: string | null
  carton_tag: string | null
  tracking_code: string | null
  cbm: string | null
  length_cm: string | null
  width_cm: string | null
  height_cm: string | null
  received_date: string | null
  loading_date?: string | null
  declared_value_usd: string | null
  // Bulk-package fields from a forwarder manifest import (migration 040).
  // One row can be "16 bags", so quantity is not always 1.
  quantity?: number | null
  package_unit?: string | null
  /** Verbatim source cell, e.g. "1PALLET(61items)" — kept when it was compound. */
  quantity_raw?: string | null
  /** Verbatim BALE TYPE, e.g. "BIG BALE"; package_unit collapses to 'bale'. */
  bale_type?: string | null
  bale_no?: string | null  /** Set when this row came from a quantity entry; shared by the whole batch.
   *  Null for rows keyed or imported one at a time. */
  batch_ref?: string | null

}

export interface ItemRejectionEntry {
  item_id: string
  reason: string
}

export interface ApprovalCommentEntry {
  actor_id: string
  comments: string
  item_rejections: ItemRejectionEntry[]
  at: string
}

export interface PackingList {
  id: string
  tenant_id: string
  reference?: string | null
  container_id: string
  container_number: string | null
  container_parcel_number?: string | null
  container_status?: string | null
  container_ship_date?: string | null
  container_eta?: string | null
  shipping_line?: string | null
  origin?: string | null
  destination?: string | null
  vessel_name?: string | null
  voyage_number?: string | null
  customer_id: string
  customer_name?: string | null
  customer_phone?: string | null
  customer_whatsapp?: string | null
  loading_date?: string | null
  delivery_date?: string | null
  delivery_date_mode?: DeliveryDateMode | null
  ship_date?: string | null
  estimated_arrival_date?: string | null
  loading_receipt_number?: string | null
  loaded_at?: string | null
  supplier_name?: string | null
  supplier_phone?: string | null
  remarks?: string | null
  arrival_warehouse_id?: string | null
  arrival_warehouse_name?: string | null
  /** Total packages (sums bulk quantities), unlike carton_count which counts rows. */
  package_count?: number
  /** Packages keyed by unit, e.g. { bale: 2, bag: 16 }. */
  package_mix?: Record<string, number> | null
  status: PackingListStatus
  items: PackingListItem[]
  total_cbm: string
  total_weight_kg: string
  carton_count: number
  created_by: string | null
  created_by_name?: string | null
  approved_by: string | null
  approved_by_name?: string | null
  approved_at: string | null
  rejected_by: string | null
  rejected_by_name?: string | null
  rejected_at: string | null
  approval_comments: ApprovalCommentEntry[] | null
  created_at: string
  updated_at: string
}

/** Package types offered in the create/edit wizard. */
export type PackageUnit = 'carton' | 'bag' | 'pallet' | 'bale' | 'sack'

export const PACKAGE_UNITS: { value: PackageUnit; label: string }[] = [
  { value: 'carton', label: 'Carton' },
  { value: 'bag', label: 'Bag' },
  { value: 'pallet', label: 'Pallet' },
  { value: 'bale', label: 'Bale' },
  { value: 'sack', label: 'Sack' },
]

export interface PackingListItemInput {
  description: string
  weight_dispatch_kg?: number
  weight_actual_kg?: number
  length_cm?: number
  width_cm?: number
  height_cm?: number
  received_date?: string
  loading_date?: string
  declared_value_usd?: number
  package_unit?: PackageUnit
  /**
   * How many identical packages this line stands for. The SERVER expands it
   * into that many rows, each with its own carton tag and its own CBM — it is
   * not stored as a quantity on one row, because nothing downstream multiplies
   * CBM by quantity, so one row would bill N packages as one.
   *
   * Which means the totals shown beside the form must multiply by it, or the
   * figures (and the live shipping price) understate what is being created.
   */
  quantity?: number
  /** Required by the API whenever quantity > 1; the form gates on it too. */
  identical_confirmed?: boolean
  /** Groups the rows one quantity entry produced. Round-tripped on edit. */
  batch_ref?: string | null
}

export interface CreatePackingListInput {
  container_id: string
  customer_id: string
  loading_date?: string
  delivery_date?: string
  delivery_date_mode?: DeliveryDateMode
  supplier_name?: string
  supplier_phone?: string
  remarks?: string
  arrival_warehouse_id?: string
  items: PackingListItemInput[]
}

export interface UpdatePackingListItemInput extends PackingListItemInput {
  id?: string
}

export interface UpdatePackingListInput {
  loading_date?: string
  delivery_date?: string
  delivery_date_mode?: DeliveryDateMode
  supplier_name?: string
  supplier_phone?: string
  remarks?: string
  arrival_warehouse_id?: string
  items: UpdatePackingListItemInput[]
}

export interface PackingListDocumentInfo {
  available: boolean
  finalized?: boolean
  reference?: string | null
  loaded_at?: string | null
  ship_date?: string | null
  estimated_arrival_date?: string | null
  lang: DocumentLang
  page_count: number
  image_eligible: boolean
  image_disabled_reason: string | null
}

export interface PackingListDocumentsResponse {
  packing_list_id: string
  customer_phone?: string | null
  customer_whatsapp?: string | null
  loading_receipt: PackingListDocumentInfo
  packing_list: PackingListDocumentInfo
}

export interface ShareWhatsAppResponse {
  document_type: 'loading_receipt' | 'packing_list'
  format_sent: 'image' | 'pdf'
  page_count: number
  lang: DocumentLang
  recipient_phone: string
  filename: string
  message_id?: string | null
  notice?: string | null
}

export interface RejectPackingListInput {
  comments: string
  item_rejections?: ItemRejectionEntry[]
}

export interface BulkActionFailure {
  id: string
  reason: string
}

export interface BulkActionResult {
  succeeded: string[]
  failed: BulkActionFailure[]
}

export interface PackingListListParams {
  cursor?: string
  limit?: number
  status?: string
  container_id?: string
  customer_id?: string
  q?: string
}

export const packingListApi = {
  list: (params: PackingListListParams = {}) =>
    apiRequestList<PackingList>({
      method: 'GET',
      path: '/v1/packing-lists',
      query: params as Record<string, string | number | undefined>,
    }),

  listByContainer: (containerId: string, params: Omit<PackingListListParams, 'container_id'> = {}) =>
    apiRequestList<PackingList>({
      method: 'GET',
      path: `/v1/containers/${containerId}/packing-lists`,
      query: params as Record<string, string | number | undefined>,
    }),

  get: (id: string) => apiRequest<PackingList>({ method: 'GET', path: `/v1/packing-lists/${id}` }),

  create: (body: CreatePackingListInput, idempotencyKey: string) =>
    apiRequest<PackingList>({ method: 'POST', path: '/v1/packing-lists', body, idempotencyKey }),

  update: (id: string, body: UpdatePackingListInput) =>
    apiRequest<PackingList>({ method: 'PUT', path: `/v1/packing-lists/${id}`, body }),

  submit: (id: string) => apiRequest<PackingList>({ method: 'PATCH', path: `/v1/packing-lists/${id}/submit` }),

  approve: (id: string, comments?: string) =>
    apiRequest<PackingList>({ method: 'PATCH', path: `/v1/packing-lists/${id}/approve`, body: { comments } }),

  reject: (id: string, body: RejectPackingListInput) =>
    apiRequest<PackingList>({ method: 'PATCH', path: `/v1/packing-lists/${id}/reject`, body }),

  // draft -> pending_approval. An import creates dozens of lists at once, so
  // moving them forward one at a time is not workable.
  bulkSubmit: (ids: string[]) =>
    apiRequest<BulkActionResult>({ method: 'POST', path: '/v1/packing-lists/bulk-submit', body: { ids } }),

  bulkApprove: (ids: string[], comments?: string) =>
    apiRequest<BulkActionResult>({ method: 'POST', path: '/v1/packing-lists/bulk-approve', body: { ids, comments } }),

  bulkReject: (ids: string[], comments: string) =>
    apiRequest<BulkActionResult>({ method: 'POST', path: '/v1/packing-lists/bulk-reject', body: { ids, comments } }),

  /** xlsx or csv export — triggers browser download. */
  export: (id: string, format: Exclude<ExportFormat, 'pdf' | 'png'>) =>
    apiDownloadFile(`/v1/packing-lists/${id}/export`, format, `packing-list-${id}.${format}`),

  /** Packing List PDF export — opens in new browser tab. */
  pdf: (id: string, lang: DocumentLang = 'en') =>
    apiDownloadFile(`/v1/packing-lists/${id}/pdf`, 'pdf', `packing-list-${id}-${lang}.pdf`, { lang }),

  /** Packing List single-page PNG image export (422 if > 1 page). */
  image: (id: string, lang: DocumentLang = 'en') =>
    apiDownloadFile(`/v1/packing-lists/${id}/image`, 'png', `packing-list-${id}-${lang}.png`, { lang }),

  /** Bilingual Loading Receipt PDF (defaults to Chinese). */
  loadingReceiptPdf: (id: string, lang: DocumentLang = 'zh') =>
    apiDownloadFile(
      `/v1/packing-lists/${id}/loading-receipt/pdf`,
      'pdf',
      `loading-receipt-${id}-${lang}.pdf`,
      { lang },
    ),

  /** Bilingual Loading Receipt single-page PNG image (422 if > 1 page). */
  loadingReceiptImage: (id: string, lang: DocumentLang = 'zh') =>
    apiDownloadFile(
      `/v1/packing-lists/${id}/loading-receipt/image`,
      'png',
      `loading-receipt-${id}-${lang}.png`,
      { lang },
    ),

  /** Dual-format & multi-page eligibility metadata for both documents. */
  documents: (id: string, opts?: { lang_lr?: DocumentLang; lang_pl?: DocumentLang }) =>
    apiRequest<PackingListDocumentsResponse>({
      method: 'GET',
      path: `/v1/packing-lists/${id}/documents`,
      query: { lang_lr: opts?.lang_lr ?? 'zh', lang_pl: opts?.lang_pl ?? 'en' },
    }),

  /** Share Loading Receipt or Packing List with customer via WhatsApp (image for 1-page, PDF for multi-page). */
  shareWhatsApp: (
    id: string,
    body: { document_type: 'loading_receipt' | 'packing_list'; lang?: DocumentLang },
  ) =>
    apiRequest<ShareWhatsAppResponse>({
      method: 'POST',
      path: `/v1/packing-lists/${id}/share-whatsapp`,
      body,
    }),
}
