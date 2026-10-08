import { beforeEach, describe, expect, it, vi } from 'vitest'
import { registerSessionActions } from '../auth/sessionBridge'
import { clearActiveTokens, setActiveTokens } from '../auth/tokenStore'
import { containersApi } from './tracking'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('containersApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    setActiveTokens({ idToken: 'tok', tokenType: 'cognito' })
    registerSessionActions({ refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() })
  })

  it('list() hits GET /v1/containers with query params', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }))
    await containersApi.list({ status: 'loading', q: 'MSCU' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/containers?')
    expect(url).toContain('status=loading')
    expect(url).toContain('q=MSCU')
    expect(init.method).toBe('GET')
  })

  it('get() hits GET /v1/containers/:id', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'c1', container_number: 'MSCU1234567' } }))
    const result = await containersApi.get('c1')
    expect(fetchMock.mock.calls[0]?.[0]).toContain('/v1/containers/c1')
    expect(result).toEqual({ id: 'c1', container_number: 'MSCU1234567' })
  })

  it('create() POSTs with the idempotency key', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'c1' } }))
    await containersApi.create({ container_number: 'MSCU1234567' }, 'idem-1')
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }]
    expect(init.method).toBe('POST')
    expect(init.headers['Idempotency-Key']).toBe('idem-1')
    expect(init.body).toBe(JSON.stringify({ container_number: 'MSCU1234567' }))
  })

  it('updateStatus() PATCHes /v1/containers/:id/status', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'c1', status: 'sealed' } }))
    await containersApi.updateStatus('c1', { new_status: 'sealed' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/containers/c1/status')
    expect(init.method).toBe('PATCH')
  })

  it('events() returns the ordered event list', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ data: [{ id: 'e1', from_status: 'loading', to_status: 'sealed', actor_id: 'u1', notes: null, created_at: '2026-01-01' }] }),
    )
    const events = await containersApi.events('c1')
    expect(events).toHaveLength(1)
    expect(fetchMock.mock.calls[0]?.[0]).toContain('/v1/containers/c1/events')
  })
})
