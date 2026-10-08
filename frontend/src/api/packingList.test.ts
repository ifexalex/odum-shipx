import { beforeEach, describe, expect, it, vi } from 'vitest'
import { registerSessionActions } from '../auth/sessionBridge'
import { clearActiveTokens, setActiveTokens } from '../auth/tokenStore'
import { packingListApi } from './packingList'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('packingListApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    setActiveTokens({ idToken: 'tok', tokenType: 'cognito' })
    registerSessionActions({ refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() })
  })

  it('list() hits GET /v1/packing-lists with filters', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }))
    await packingListApi.list({ status: 'pending_approval' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/packing-lists?')
    expect(url).toContain('status=pending_approval')
    expect(init.method).toBe('GET')
  })

  it('listByContainer() hits GET /v1/containers/:id/packing-lists', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }))
    await packingListApi.listByContainer('c1')
    expect(fetchMock.mock.calls[0]?.[0]).toContain('/v1/containers/c1/packing-lists')
  })

  it('create() POSTs with idempotency key', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'pl1' } }))
    await packingListApi.create({ container_id: 'c1', customer_id: 'cust1', items: [] }, 'idem-1')
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }]
    expect(init.method).toBe('POST')
    expect(init.headers['Idempotency-Key']).toBe('idem-1')
  })

  it('submit() PATCHes the /submit endpoint', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'pl1', status: 'pending_approval' } }))
    await packingListApi.submit('pl1')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/packing-lists/pl1/submit')
    expect(init.method).toBe('PATCH')
  })

  it('approve() PATCHes the /approve endpoint', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'pl1', status: 'approved' } }))
    await packingListApi.approve('pl1', 'looks good')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/packing-lists/pl1/approve')
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe(JSON.stringify({ comments: 'looks good' }))
  })

  it('reject() PATCHes the /reject endpoint with comments + item rejections', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'pl1', status: 'rejected' } }))
    await packingListApi.reject('pl1', { comments: 'bad', item_rejections: [{ item_id: 'i1', reason: 'wrong dims' }] })
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/packing-lists/pl1/reject')
  })

  it('bulkApprove() posts ids + optional comments', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { succeeded: ['pl1', 'pl2'], failed: [] } }))
    const result = await packingListApi.bulkApprove(['pl1', 'pl2'])
    expect(fetchMock.mock.calls[0]?.[0]).toContain('/v1/packing-lists/bulk-approve')
    expect(result.succeeded).toEqual(['pl1', 'pl2'])
  })

  it('bulkReject() returns per-item failures', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ data: { succeeded: ['pl1'], failed: [{ id: 'pl2', reason: 'already approved' }] } }),
    )
    const result = await packingListApi.bulkReject(['pl1', 'pl2'], 'bad batch')
    expect(result.failed).toEqual([{ id: 'pl2', reason: 'already approved' }])
  })
})
