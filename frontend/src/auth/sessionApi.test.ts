import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { establishServerSession, revokeServerSession, silentRefresh } from './sessionApi'

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('sessionApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  describe('establishServerSession', () => {
    it('POSTs the refresh token with credentials included', async () => {
      fetchMock.mockResolvedValue(new Response(null, { status: 204 }))

      await establishServerSession('a-cognito-refresh-token')

      expect(fetchMock).toHaveBeenCalledOnce()
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(url).toBe('https://api.test.shipx.co/v1/auth/session')
      expect(init.method).toBe('POST')
      expect(init.credentials).toBe('include')
      expect(JSON.parse(init.body as string)).toEqual({ refresh_token: 'a-cognito-refresh-token' })
    })

    it('throws when the backend rejects the request', async () => {
      fetchMock.mockResolvedValue(new Response(null, { status: 422 }))
      await expect(establishServerSession('bad')).rejects.toThrow('422')
    })
  })

  describe('silentRefresh', () => {
    it('returns the fresh ID token on success, with credentials included', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ data: { id_token: 'fresh.id.token', expires_in: 3600 } }))

      const result = await silentRefresh()

      expect(result).toEqual({
        idToken: 'fresh.id.token',
        expiresIn: 3600,
        tenantId: null,
        role: null,
      })
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(url).toBe('https://api.test.shipx.co/v1/auth/refresh')
      expect(init.method).toBe('POST')
      expect(init.credentials).toBe('include')
    })

    it('returns null (never throws) when there is no valid session cookie', async () => {
      fetchMock.mockResolvedValue(new Response(null, { status: 401 }))
      await expect(silentRefresh()).resolves.toBeNull()
    })

    it('returns null (never throws) on a network failure', async () => {
      fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
      await expect(silentRefresh()).resolves.toBeNull()
    })

    it('returns null when VITE_API_BASE_URL is missing, instead of throwing', async () => {
      vi.unstubAllEnvs()
      await expect(silentRefresh()).resolves.toBeNull()
    })
  })

  describe('revokeServerSession', () => {
    it('POSTs to the logout endpoint with credentials included', async () => {
      fetchMock.mockResolvedValue(new Response(null, { status: 204 }))

      await revokeServerSession()

      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(url).toBe('https://api.test.shipx.co/v1/auth/logout')
      expect(init.method).toBe('POST')
      expect(init.credentials).toBe('include')
    })

    it('never throws, even on a network failure', async () => {
      fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
      await expect(revokeServerSession()).resolves.toBeUndefined()
    })
  })
})
