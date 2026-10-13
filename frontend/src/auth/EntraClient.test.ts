import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { refreshSession, signIn } from './EntraClient'

describe('EntraClient (backend ROPC proxy)', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  function mockResponse(body: Record<string, unknown>, ok = true, status = 200): void {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) }),
    )
  }

  it('signIn posts credentials to the backend /v1/auth/login and maps the envelope', async () => {
    mockResponse({ data: { id_token: 'id.jwt', access_token: 'acc', refresh_token: 'ref' } })

    const tokens = await signIn('user@x.com', 'pw')

    expect(tokens).toEqual({ idToken: 'id.jwt', accessToken: 'acc', refreshToken: 'ref' })
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    const call = fetchMock.mock.calls[0]!
    expect(call[0] as string).toBe('https://api.example.test/v1/auth/login')
    const init = call[1] as { body: string; method: string }
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ username: 'user@x.com', password: 'pw' })
  })

  it('maps a 401 from the proxy to a credentials message', async () => {
    mockResponse({ detail: 'Authentication required', error_code: 'AUTHENTICATION_REQUIRED' }, false, 401)

    await expect(signIn('user@x.com', 'wrong')).rejects.toMatchObject({
      message: 'Check your email and password and try again.',
    })
  })

  it('refreshSession rejects — refresh is server-side via the session cookie', async () => {
    await expect(refreshSession()).rejects.toThrow(/server-side/i)
  })
})
