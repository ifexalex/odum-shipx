import { beforeEach, describe, expect, it, vi } from 'vitest'
import { registerSessionActions } from '../auth/sessionBridge'
import { clearActiveTokens, setActiveTokens } from '../auth/tokenStore'
import { manifestApi } from './manifest'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('manifestApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    setActiveTokens({ idToken: 'tok', tokenType: 'cognito' })
    registerSessionActions({ refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() })
  })

  it('list() hits GET /v1/manifests with filters', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }))
    await manifestApi.list({ verification_status: 'pending' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/manifests?')
    expect(url).toContain('verification_status=pending')
    expect(init.method).toBe('GET')
  })

  it('get() hits GET /v1/manifests/:id', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'mf1' } }))
    await manifestApi.get('mf1')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/manifests/mf1')
    expect(init.method).toBe('GET')
  })

  it('verify() PATCHes /verify with the verification body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'mf1', verification_status: 'verified' } }))
    await manifestApi.verify('mf1', { verification_status: 'verified' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/manifests/mf1/verify')
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe(JSON.stringify({ verification_status: 'verified' }))
  })

  it('verify() sends discrepancies when logging missing/damaged items', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'mf1', verification_status: 'discrepancies_found' } }))
    const discrepancies = [{ customer_id: 'cust1', carton_tags: ['SHX-00024'], type: 'missing' as const, notes: 'not found' }]
    await manifestApi.verify('mf1', { verification_status: 'discrepancies_found', discrepancies })
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.body).toBe(JSON.stringify({ verification_status: 'discrepancies_found', discrepancies }))
  })

  it('resolveDiscrepancy() PATCHes /resolve-discrepancy', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'mf1', verification_status: 'resolved' } }))
    await manifestApi.resolveDiscrepancy('mf1', { resolution_notes: 'Recounted, all found.' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/manifests/mf1/resolve-discrepancy')
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe(JSON.stringify({ resolution_notes: 'Recounted, all found.' }))
  })

  it('getEvidenceUploadUrl() POSTs /evidence with filename, content_type and label', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ data: { upload_url: 'https://s3', fields: {}, evidence_id: 'ev1', file_key: 'k' } }),
    )
    await manifestApi.getEvidenceUploadUrl('mf1', 'damage.jpg', 'image/jpeg', 'Missing — Acme (SHX-1)')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/manifests/mf1/evidence')
    expect(init.method).toBe('POST')
    expect(init.body).toBe(
      JSON.stringify({ filename: 'damage.jpg', content_type: 'image/jpeg', label: 'Missing — Acme (SHX-1)' }),
    )
  })
})
