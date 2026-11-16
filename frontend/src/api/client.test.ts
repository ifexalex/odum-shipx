import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../lib/queryClient'
import { registerSessionActions } from '../auth/sessionBridge'
import { clearTenantBlocked, getTenantBlocked } from '../auth/tenantGate'
import { clearActiveTokens, setActiveLocalAuth, setActiveTokens } from '../auth/tokenStore'
import { ApiError, AuthExpiredError, apiDownloadFile, apiRequest } from './client'

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

function problemResponse(status: number, overrides: Partial<Record<string, unknown>> = {}, init: ResponseInit = {}): Response {
  return new Response(
    JSON.stringify({
      type: `https://errors.logistics-api.com/some-error`,
      title: 'Some error',
      status,
      detail: 'Something went wrong.',
      error_code: 'SOME_ERROR',
      ...overrides,
    }),
    { status, headers: { 'Content-Type': 'application/problem+json' }, ...init },
  )
}

interface CapturedRequest {
  url: string
  init: RequestInit & { headers: Record<string, string> }
}

function capturedRequest(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): CapturedRequest {
  const call = fetchMock.mock.calls[callIndex] as [string, RequestInit & { headers: Record<string, string> }]
  return { url: call[0], init: call[1] }
}

describe('apiRequest', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    clearTenantBlocked()
    registerSessionActions({
      refreshNow: vi.fn().mockResolvedValue(undefined),
      logout: vi.fn(),
      exitImpersonation: vi.fn(),
    })
  })

  it('unwraps the data envelope on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: '1', name: 'Container A' } }))
    const result = await apiRequest<{ id: string; name: string }>({ method: 'GET', path: '/v1/containers/1' })
    expect(result).toEqual({ id: '1', name: 'Container A' })
  })

  it('returns undefined for a 204 No Content', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    const result = await apiRequest<void>({ method: 'DELETE', path: '/v1/containers/1' })
    expect(result).toBeUndefined()
  })

  it('attaches the Authorization header from the active session', async () => {
    setActiveTokens({ idToken: 'abc123', tokenType: 'cognito' })
    fetchMock.mockResolvedValue(jsonResponse({ data: {} }))
    await apiRequest({ method: 'GET', path: '/v1/containers' })
    const { init } = capturedRequest(fetchMock)
    expect(init.headers.Authorization).toBe('Bearer abc123')
  })

  it('attaches the local dev header trio when running against the Flask shim', async () => {
    setActiveLocalAuth({ tenantId: 'PLATFORM', role: 'platform_admin', roles: ['platform_admin'], userId: 'u1' })
    fetchMock.mockResolvedValue(jsonResponse({ data: {} }))
    await apiRequest({ method: 'GET', path: '/v1/containers' })
    const { init } = capturedRequest(fetchMock)
    expect(init.headers['X-Tenant-ID']).toBe('PLATFORM')
    expect(init.headers['X-Role']).toBe('platform_admin')
  })

  it('attaches Idempotency-Key when provided', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: {} }))
    await apiRequest({ method: 'POST', path: '/v1/containers', body: { name: 'x' }, idempotencyKey: 'key-1' })
    const { init } = capturedRequest(fetchMock)
    expect(init.headers['Idempotency-Key']).toBe('key-1')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ name: 'x' }))
  })

  it('builds query params, skipping undefined values', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [] }))
    await apiRequest({ method: 'GET', path: '/v1/containers', query: { cursor: undefined, limit: 20 } })
    const { url } = capturedRequest(fetchMock)
    expect(url).toContain('limit=20')
    expect(url).not.toContain('cursor=')
  })

  it('parses an RFC 7807 error body and throws ApiError with the request id', async () => {
    fetchMock.mockResolvedValue(
      problemResponse(404, { error_code: 'RESOURCE_NOT_FOUND', detail: 'Container not found.' }, {
        headers: { 'Content-Type': 'application/problem+json', 'X-Request-Id': 'req-123' },
      }),
    )
    const err: unknown = await apiRequest({ method: 'GET', path: '/v1/containers/missing' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiErr = err as ApiError
    expect(apiErr.status).toBe(404)
    expect(apiErr.errorCode).toBe('RESOURCE_NOT_FOUND')
    expect(apiErr.requestId).toBe('req-123')
  })

  it('falls back to a synthetic error shape when the error body is not JSON', async () => {
    fetchMock.mockResolvedValue(new Response('<html>502</html>', { status: 502 }))
    const err: unknown = await apiRequest({ method: 'GET', path: '/v1/containers' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiErr = err as ApiError
    expect(apiErr.status).toBe(502)
    expect(apiErr.errorCode).toBe('UNKNOWN_ERROR')
  })

  it('on 401: refreshes once and replays the request successfully', async () => {
    setActiveTokens({ idToken: 'stale', tokenType: 'cognito' })
    const refreshNow = vi.fn().mockImplementation(async () => {
      setActiveTokens({ idToken: 'fresh', tokenType: 'cognito' })
    })
    registerSessionActions({ refreshNow, logout: vi.fn(), exitImpersonation: vi.fn() })

    fetchMock
      .mockResolvedValueOnce(problemResponse(401, { error_code: 'AUTHENTICATION_REQUIRED' }))
      .mockResolvedValueOnce(jsonResponse({ data: { ok: true } }))

    const result = await apiRequest<{ ok: boolean }>({ method: 'GET', path: '/v1/containers' })

    expect(refreshNow).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(capturedRequest(fetchMock, 1).init.headers.Authorization).toBe('Bearer fresh')
    expect(result).toEqual({ ok: true })
  })

  it('on 401: logs out and throws AuthExpiredError if refresh fails', async () => {
    const logout = vi.fn()
    const refreshNow = vi.fn().mockRejectedValue(new Error('refresh token expired'))
    registerSessionActions({ refreshNow, logout, exitImpersonation: vi.fn() })
    fetchMock.mockResolvedValue(problemResponse(401, { error_code: 'AUTHENTICATION_REQUIRED' }))

    await expect(apiRequest({ method: 'GET', path: '/v1/containers' })).rejects.toBeInstanceOf(AuthExpiredError)
    expect(logout).toHaveBeenCalledOnce()
  })

  it('on 401: logs out and throws AuthExpiredError if the replay is still 401', async () => {
    const logout = vi.fn()
    registerSessionActions({ refreshNow: vi.fn().mockResolvedValue(undefined), logout, exitImpersonation: vi.fn() })
    fetchMock.mockResolvedValue(problemResponse(401, { error_code: 'AUTHENTICATION_REQUIRED' }))

    await expect(apiRequest({ method: 'GET', path: '/v1/containers' })).rejects.toBeInstanceOf(AuthExpiredError)
    expect(logout).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('normalizes a raw fetch rejection (offline/DNS/CORS) into an ApiError', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const err: unknown = await apiRequest({ method: 'GET', path: '/v1/containers' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiErr = err as ApiError
    expect(apiErr.status).toBe(0)
    expect(apiErr.errorCode).toBe('NETWORK_ERROR')
  })

  it('on 401 while impersonating: exits impersonation instead of refreshing, and never calls refreshNow', async () => {
    setActiveTokens({ idToken: 'imp-token', tokenType: 'impersonation' })
    const refreshNow = vi.fn()
    const exitImpersonation = vi.fn()
    registerSessionActions({ refreshNow, logout: vi.fn(), exitImpersonation })
    fetchMock.mockResolvedValue(problemResponse(401, { error_code: 'AUTHENTICATION_REQUIRED' }))

    await expect(apiRequest({ method: 'GET', path: '/v1/containers' })).rejects.toBeInstanceOf(AuthExpiredError)
    expect(exitImpersonation).toHaveBeenCalledOnce()
    expect(refreshNow).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('tenant-blocked gate wiring (16.12 / A4)', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    clearTenantBlocked()
    setActiveTokens({ idToken: 'tok', tokenType: 'cognito' })
    registerSessionActions({
      refreshNow: vi.fn().mockResolvedValue(undefined),
      logout: vi.fn(),
      exitImpersonation: vi.fn(),
    })
  })

  it('trips the gate when a response carries TENANT_OFFBOARDED', async () => {
    fetchMock.mockResolvedValue(
      problemResponse(410, { error_code: 'TENANT_OFFBOARDED', detail: 'Tenant t1 is offboarded' }),
    )
    await expect(apiRequest({ method: 'GET', path: '/v1/containers' })).rejects.toThrow()
    expect(getTenantBlocked()).toBe('offboarded')
  })

  it('trips the gate when a response carries TENANT_SUSPENDED', async () => {
    fetchMock.mockResolvedValue(
      problemResponse(403, { error_code: 'TENANT_SUSPENDED', detail: 'Tenant t1 is suspended' }),
    )
    await expect(apiRequest({ method: 'GET', path: '/v1/containers' })).rejects.toThrow()
    expect(getTenantBlocked()).toBe('suspended')
  })

  it('leaves the gate alone for ordinary errors', async () => {
    fetchMock.mockResolvedValue(problemResponse(403, { error_code: 'INSUFFICIENT_PERMISSIONS' }))
    await expect(apiRequest({ method: 'GET', path: '/v1/containers' })).rejects.toThrow()
    expect(getTenantBlocked()).toBeNull()
  })
})

// Ground-truth fix (2026-07-19) — every export/pdf Lambda route responds
// with a JSON envelope wrapping a presigned S3 download_url, never raw file
// bytes. apiDownloadFile previously called response.blob() directly on that
// JSON body, so every "download" opened/saved the metadata JSON instead of
// the actual document (surfaced via the customer "Download invoice" button).
describe('apiDownloadFile', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let openSpy: ReturnType<typeof vi.fn>
  let clickSpy: ReturnType<typeof vi.fn<() => void>>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    clearTenantBlocked()
    registerSessionActions({
      refreshNow: vi.fn().mockResolvedValue(undefined),
      logout: vi.fn(),
      exitImpersonation: vi.fn(),
    })
    openSpy = vi.fn()
    vi.stubGlobal('open', openSpy)
    clickSpy = vi.fn<() => void>()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(clickSpy)
  })

  const EXPORT_ENVELOPE = {
    data: {
      filename: 'billing-b1.pdf',
      download_url: 'http://localhost:5100/logistics-assets/t1/exports/2026-07-19/billing-b1.pdf?Signature=abc',
      expires_at: '2026-07-19T02:16:06Z',
      file_size_bytes: 2095,
      format: 'pdf',
    },
  }

  it('opens the presigned download_url in a new tab for pdf — not the JSON envelope itself', async () => {
    fetchMock.mockResolvedValue(jsonResponse(EXPORT_ENVELOPE))

    await apiDownloadFile('/v1/billing/b1/export', 'pdf', 'billing-b1.pdf')

    expect(openSpy).toHaveBeenCalledWith(EXPORT_ENVELOPE.data.download_url, '_blank', 'noopener,noreferrer')
  })

  it('triggers an <a download> against the presigned URL for xlsx, using the server-provided filename', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ data: { ...EXPORT_ENVELOPE.data, filename: 'billing-b1.xlsx', format: 'xlsx' } }),
    )

    await apiDownloadFile('/v1/billing/b1/export', 'xlsx', 'fallback.xlsx')

    expect(clickSpy).toHaveBeenCalledTimes(1)
  })

  it('throws ApiError on a non-ok response instead of trying to open an error body', async () => {
    fetchMock.mockResolvedValue(problemResponse(404, { error_code: 'RESOURCE_NOT_FOUND', detail: 'billing not found' }))

    await expect(apiDownloadFile('/v1/billing/b1/export', 'pdf', 'billing-b1.pdf')).rejects.toThrow(ApiError)
    expect(openSpy).not.toHaveBeenCalled()
  })

  it('forwards a list export\'s filters and sort alongside the format', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { ...EXPORT_ENVELOPE.data, filename: 'invoices.csv', format: 'csv' } }))

    await apiDownloadFile('/v1/billing/export', 'csv', 'invoices.csv', {
      status: 'unpaid,paid',
      q: 'ngozi',
      created_after: '2026-01-01',
      sort: 'billed_at',
      direction: 'desc',
      cursor: undefined,
    })

    const url = new URL(fetchMock.mock.calls[0]![0] as string)
    expect(url.pathname).toBe('/v1/billing/export')
    const sent: Record<string, string> = {}
    url.searchParams.forEach((value, key) => {
      sent[key] = value
    })
    expect(sent).toEqual({
      status: 'unpaid,paid',
      q: 'ngozi',
      created_after: '2026-01-01',
      sort: 'billed_at',
      direction: 'desc',
      format: 'csv',
    })
  })

  it('lets the format argument win over a stray format in the query', async () => {
    fetchMock.mockResolvedValue(jsonResponse(EXPORT_ENVELOPE))
    await apiDownloadFile('/v1/billing/export', 'xlsx', 'x.xlsx', { format: 'pdf' })
    expect(new URL(fetchMock.mock.calls[0]![0] as string).searchParams.get('format')).toBe('xlsx')
  })
})

describe('apiRequest — cache invalidation on writes', () => {
  // Proves the WIRING, not just the registry. cacheInvalidation.test.ts asserts
  // every path has a rule; these assert the client actually applies it, which is
  // the half that was missing and caused a deleted container to stay on screen.
  let fetchMock: ReturnType<typeof vi.fn>
  let invalidateSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    clearTenantBlocked()
    registerSessionActions({
      refreshNow: vi.fn().mockResolvedValue(undefined),
      logout: vi.fn(),
      exitImpersonation: vi.fn(),
    })
    invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)
  })

  afterEach(() => {
    invalidateSpy.mockRestore()
  })

  const invalidatedRoots = (): unknown[][] =>
    (invalidateSpy.mock.calls as unknown as [{ queryKey: unknown[] }][]).map(
      ([arg]) => arg.queryKey,
    )

  it('invalidates containers and packing lists when a container is deleted', async () => {
    // The exact reported bug.
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'c1' } }))
    await apiRequest({ method: 'DELETE', path: '/v1/containers/c1' })
    expect(invalidatedRoots()).toEqual(
      expect.arrayContaining([['containers'], ['packing-lists']]),
    )
  })

  it('does not invalidate anything on a GET', async () => {
    // Invalidating on reads is how you build a refetch loop.
    fetchMock.mockResolvedValue(jsonResponse({ data: [] }))
    await apiRequest({ method: 'GET', path: '/v1/containers' })
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('does not invalidate when the write fails', async () => {
    // A rejected write changed nothing, so refetching would be pure waste —
    // and would mask the failure by repainting the list.
    fetchMock.mockResolvedValue(problemResponse(409))
    await expect(apiRequest({ method: 'POST', path: '/v1/containers' })).rejects.toThrow(ApiError)
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('still returns the response when invalidation itself throws', async () => {
    // A cache problem must never turn a write that actually succeeded into an
    // error the user sees.
    invalidateSpy.mockImplementation(() => {
      throw new Error('cache exploded')
    })
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'c1' } }))
    await expect(apiRequest({ method: 'DELETE', path: '/v1/containers/c1' })).resolves.toEqual({ id: 'c1' })
  })

  it('reaches billing and containers when a packing list is approved', async () => {
    // Cross-domain: approval consumes container CBM and can generate billing,
    // neither of which the request path mentions.
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'pl1' } }))
    await apiRequest({ method: 'PATCH', path: '/v1/packing-lists/pl1/approve' })
    expect(invalidatedRoots()).toEqual(
      expect.arrayContaining([['packing-lists'], ['containers'], ['billing']]),
    )
  })

  it('invalidates nothing for a pre-auth path', async () => {
    // Mapped to an empty root set, so it matches but invalidates nothing.
    fetchMock.mockResolvedValue(jsonResponse({ data: { ok: true } }))
    await apiRequest({ method: 'POST', path: '/v1/onboarding-requests' })
    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})
