import { queryClient } from '../lib/queryClient'
import { getSessionActions } from '../auth/sessionBridge'
import { ruleForPath } from './cacheInvalidation'
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

/**
 * What a person reads for an error (FD-20). A 409 or 422 carries the server's own words, which are written for users
 * ("The file is larger than 5 MB."). Anything else is a system message ("Insufficient permissions for this operation.
 * Required role: platform_admin"), so it gets plain words; the server's text stays on `detail` for logs and support.
 */
export function plainErrorMessage(status: number, serverText: string, errorCode?: string): string {
  // A payment provider's refusal is written for the user ("Paystack rejected this key — check it's correct").
  if (status === 409 || status === 422 || status === 400 || errorCode === 'EXTERNAL_SERVICE_ERROR') return serverText
  if (status === 403) return "You don't have permission to do this. Ask your admin if you need it."
  if (status === 404) return "We couldn't find that. It may have been removed, or the link is out of date."
  if (status === 429) return 'Too many requests just now. Wait a moment and try again.'
  // Maintenance answers every request with 503; say so rather than blaming the user's connection (audit PA-01).
  if (errorCode === 'MAINTENANCE_MODE') return serverText
  if (status === 0 || status === 502 || status === 503 || status === 504) {
    return "We couldn't reach the server. Check your connection and try again."
  }
  if (status >= 500) return 'Something went wrong on our side. Try again; if it keeps happening, contact support.'
  return serverText
}

export class ApiError extends Error {
  /** The server's own text, unchanged (`message` may be plainer). */
  readonly detail: string
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
    super(plainErrorMessage(shape.status, shape.detail || shape.title, shape.error_code))
    this.detail = shape.detail || shape.title
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

async function parseError(response: Response, path = ''): Promise<ApiError> {
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
  // leaving each page to render its own error banner. Never trip the tenant gate
  // from platform-admin management routes (/v1/platform/*).
  if (!path.startsWith('/v1/platform/')) {
    reportTenantBlocked(shape.error_code)
  }
  return new ApiError(shape, requestId)
}

/**
 * Invalidate the query roots a successful write affects.
 *
 * Fire-and-forget by design: a cache problem must never turn a write that
 * actually succeeded into an error the user sees, so nothing here is awaited or
 * allowed to throw. An unmapped path is reported in dev only — the drift test in
 * cacheInvalidation.test.ts is what enforces coverage, and a console error in
 * production would be noise the user cannot act on.
 */
function invalidateForRequest(method: string, path: string): void {
  if (method === 'GET') return
  try {
    const rule = ruleForPath(path)
    if (!rule) {
      if (import.meta.env.DEV) {
        console.warn(
          `[ShipX] No cache-invalidation rule for ${method} ${path}. ` +
            'Add one in api/cacheInvalidation.ts, or the UI will show stale data after this write.',
        )
      }
      return
    }
    for (const root of rule.roots) {
      void queryClient.invalidateQueries({ queryKey: root })
    }
  } catch {
    // Deliberately swallowed — see the note above.
  }
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
    throw await parseError(response, opts.path)
  }

  // A successful write makes some cached reads wrong. Doing this here, rather
  // than at each call site, is what makes queryClient.ts's stated assumption
  // ("mutations call invalidateQueries immediately") actually hold — 40 of 45
  // mutating files did not, which is why a deleted container stayed on screen
  // until a hard reload. See api/cacheInvalidation.ts.
  invalidateForRequest(opts.method, opts.path)

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

export type ExportFormat = 'xlsx' | 'csv' | 'pdf' | 'png'
/** The formats of a data export: spreadsheets only. A PDF is a document with its own route (FD-39). */
export type DataExportFormat = 'xlsx' | 'csv'

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
 *
 * `query` carries anything else the endpoint takes — a list export forwards the
 * list's own filters and sort. `format` always wins over a stray `query.format`.
 */
export async function apiDownloadFile(
  path: string,
  format: ExportFormat,
  defaultFilename: string,
  query: Record<string, string | number | undefined> = {},
): Promise<void> {
  // A PDF opens in a new tab, and the tab must be opened now, inside the click (FD-44): opened after the request
  // returns, Safari and most mobile browsers treat it as a pop-up and block it, so the button looked dead. It shows
  // a holding line until the link arrives. Must run before the first await.
  const tab = format === 'pdf' ? openPendingTab() : null
  const isDedicatedDocument = format === 'pdf' || format === 'png'
  try {
    const response = await fetchWithAuth({
      method: 'GET',
      path,
      query: isDedicatedDocument ? query : { ...query, format },
    })
    if (!response.ok) {
      throw await parseError(response, path)
    }
    const envelope = (await response.json()) as SuccessEnvelope<ExportResultShape>
    const { download_url: downloadUrl, filename } = envelope.data

    if (format === 'pdf') {
      // A blocked tab (some browsers block even this) falls back to opening the document here.
      if (tab) tab.location.replace(downloadUrl)
      else window.location.assign(downloadUrl)
    } else {
      // The API names the file on the link itself (Content-Disposition); `download` is ignored cross-origin.
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = filename ?? defaultFilename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    }
  } catch (err) {
    tab?.close()
    throw err
  }
}

/** A new tab saying the document is on its way, detached from this page; null when the browser refuses it. */
function openPendingTab(): Window | null {
  const tab = window.open('', '_blank')
  if (!tab) return null
  try {
    tab.opener = null
    tab.document.title = 'Preparing document…'
    tab.document.body.style.fontFamily = 'system-ui, sans-serif'
    tab.document.body.textContent = 'Preparing your document…'
  } catch {
    // A tab we cannot write to still receives the document's address.
  }
  return tab
}
