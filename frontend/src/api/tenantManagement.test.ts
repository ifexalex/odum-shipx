import { beforeEach, describe, expect, it, vi } from 'vitest'
import { registerSessionActions } from '../auth/sessionBridge'
import { clearActiveTokens, setActiveTokens } from '../auth/tokenStore'
import { customersApi } from './tenantManagement'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('customersApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    setActiveTokens({ idToken: 'tok', tokenType: 'cognito' })
    registerSessionActions({ refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() })
  })

  it('list() hits GET /v1/customers with the q filter', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }))
    await customersApi.list({ q: 'ngozi' })
    const [url] = fetchMock.mock.calls[0] as [string]
    expect(url).toContain('/v1/customers?')
    expect(url).toContain('q=ngozi')
  })
})
