import { getSessionActions } from '../auth/sessionBridge'
import { reportTenantBlocked } from '../auth/tenantGate'
import { getActiveTokenType, getAuthHeaders } from '../auth/tokenStore'

// RFC 7807 problem+json shape (shared/responses.py) — field names are exact,
// not camelCased, because they come straight off the wire.
export interface ApiErrorShape {
  type: string
  title: string
  status: number
  detail: string
  error_code: string
  // Present only on 422 BUSINESS_RULE_VIOLATION — names the specific rule.
  rule_id?: string
  instance?: string
  errors?: { field: string; message: string }[]
}

export class ApiError extends Error {
  readonly type: string
  readonly status: number
  readonly errorCode: string
  // Names which business rule refused the request (422 BUSINESS_RULE_VIOLATION
  // only). Lets a caller branch on the specific rule instead of matching the
  // prose message.
  readonly ruleId?: string
  readonly instance?: string
  readonly fieldErrors?: { field: string; message: string }[]
  readonly requestId: string | null

  constructor(shape: ApiErrorShape, requestId: string | null) {
    super(shape.detail || shape.title)
    this.name = 'ApiError'
    this.type = shape.type
    this.status = shape.status
    this.errorCode = shape.error_code
    this.ruleId = shape.rule_id
    this.instance = shape.instance
    this.fieldErrors = shape.errors
    this.requestId = requestId
  }
}

// Thrown when a 401 survives one silent-refresh-and-replay attempt. Callers
// don't need to distinguish "refresh failed" from "replay still 401" — both
// mean the caller must treat the session as gone.
export class AuthExpiredError extends Error {
  constructor() {
    super('Session expired — please sign in again')
    this.name = 'AuthExpiredError'
  }
}

export interface SuccessEnvelope<T> {
  data: T
  meta?: Record<string, unknown>
}

export interface PaginationMeta {
  has_more: boolean
  next_cursor: string | null
  total_count: number
}

export interface ListResponse<T> {
  data: T[]
  meta: { pagination: PaginationMeta }
}

export interface RequestOptions {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  path: string
  body?: unknown
  query?: Record<string, string | number | undefined>
  idempotencyKey?: string
}

function apiBaseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (!value) throw new Error('Missing required env var: VITE_API_BASE_URL')
  return value
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(path, apiBaseUrl())
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

// A true network failure (offline, DNS, CORS) makes fetch() reject with a raw
// TypeError, not a Response — normalize it into the same ApiError shape
// everything else throws, so callers/UI never have to special-case it.
async function doFetch(opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { ...getAuthHeaders() }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey

  try {
    return await fetch(buildUrl(opts.path, opts.query), {
      method: opts.method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    })
  } catch {
    throw new ApiError(
      {
        type: 'about:blank',
        title: 'Network Error',
        status: 0,
        detail: 'Could not reach the server. Check your connection and try again.',
        error_code: 'NETWORK_ERROR',
      },
      null,
    )
  }
}

async function parseError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get('X-Request-Id')
  let shape: ApiErrorShape
  try {
    shape = await response.json()
  } catch {
    shape = {
      type: 'about:blank',
      title: response.statusText,
      status: response.status,
      detail: 'The server returned an unreadable error response.',
      error_code: 'UNKNOWN_ERROR',
    }
  }
  // Tenant-level blocks (410 TENANT_OFFBOARDED / 403 TENANT_SUSPENDED) fail on
  // every request identically — flip the full-page gate (16.12) instead of
  // leaving each page to render its own error banner.
  reportTenantBlocked(shape.error_code)
  return new ApiError(shape, requestId)
}

// On a 401: impersonation tokens never silently refresh (they hard-expire by
// design), so a 401 while impersonating means the session was revoked or hit
// its 30-minute cap server-side — exit impersonation, don't try to refresh
// the platform admin's own (unrelated) token. For a normal session, attempt
// exactly one silent-refresh-and-replay before giving up.
async function recoverFrom401(opts: RequestOptions): Promise<Response> {
  const actions = getSessionActions()
  if (getActiveTokenType() === 'impersonation') {
    actions.exitImpersonation()
    throw new AuthExpiredError()
  }
  try {
    await actions.refreshNow()
  } catch {
    actions.logout()
    throw new AuthExpiredError()
  }
  const retried = await doFetch(opts)
  if (retried.status === 401) {
    actions.logout()
    throw new AuthExpiredError()
  }
  return retried
}

async function fetchWithAuth(opts: RequestOptions): Promise<Response> {
  let response = await doFetch(opts)

  if (response.status === 401) {
    response = await recoverFrom401(opts)
  }

  if (!response.ok) {
    throw await parseError(response)
  }

  return response
}

export async function apiRequest<T>(opts: RequestOptions): Promise<T> {
  const response = await fetchWithAuth(opts)

  if (response.status === 204) {
    return undefined as T
  }

  const envelope = (await response.json()) as SuccessEnvelope<T>
  return envelope.data
}

// Paginated list endpoints (shared/responses.py's paginated()) return
// {data: T[], meta: {pagination: {...}}} at the top level — there is no
// outer envelope to unwrap a second time. Using apiRequest<ListResponse<T>>
// here would silently double-unwrap: envelope.data would be the array
// itself, not a {data, meta} object, and result.data downstream would be
// undefined. Use this for every paginated GET instead.
export async function apiRequestList<T>(opts: RequestOptions): Promise<ListResponse<T>> {
  const response = await fetchWithAuth(opts)
  return (await response.json()) as ListResponse<T>
}

export type ExportFormat = 'xlsx' | 'csv' | 'pdf'

interface ExportResultShape {
  filename: string
  download_url: string
  expires_at: string
  file_size_bytes: number
  format: string
}

/**
 * Download a binary export file from the API.
 *
 * Ground-truth fix (2026-07-19): every export/pdf Lambda route (packing-list
 * export, packing-list pdf, manifest export, release-note pdf, billing
 * export) responds with `application/json` — {"data": {filename,
 * download_url, ...}} (shared/responses.py's success() wrapping
 * _upload_and_presign()'s result) — never the raw file bytes. This function
 * previously called response.blob() directly on that JSON body and opened
 * *that* as if it were the file, so every PDF/export button in the app
 * opened/downloaded a text file containing the JSON metadata instead of the
 * actual document. Fixed to parse the envelope and follow download_url — a
 * presigned S3 GET URL that needs no auth headers of its own.
 *
 * PDF exports open the presigned URL in a new browser tab (native PDF viewer).
 * xlsx/csv trigger a <a download> click against the same URL, forcing the
 * filename from the JSON response (S3's response has no Content-Disposition
 * override configured).
 */
export async function apiDownloadFile(path: string, format: ExportFormat, defaultFilename: string): Promise<void> {
  const response = await fetchWithAuth({ method: 'GET', path, query: { format } })

  if (!response.ok) {
    throw await parseError(response)
  }

  const envelope = (await response.json()) as SuccessEnvelope<ExportResultShape>
  const { download_url: downloadUrl, filename } = envelope.data

  if (format === 'pdf') {
    window.open(downloadUrl, '_blank', 'noopener,noreferrer')
  } else {
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = filename ?? defaultFilename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }
}
