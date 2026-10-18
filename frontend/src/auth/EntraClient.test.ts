import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { beginLogin, completeLogin, refreshSession, signIn } from './EntraClient'

describe('EntraClient (interactive BFF auth-code)', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  function mockFetch(body: Record<string, unknown>, ok = true, status = 200): ReturnType<typeof vi.fn> {
    const fn = vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) })
    vi.stubGlobal('fetch', fn)
    return fn
  }

  it('beginLogin fetches the authorize URL (with credentials) and redirects', async () => {
    const fetchMock = mockFetch({ data: { authorize_url: 'https://entra.example/authorize?x=1' } })
    const assign = vi.fn()
    vi.stubGlobal('location', { assign } as unknown as Location)

    // beginLogin never resolves (it redirects), so race it against the redirect.
    void beginLogin()
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith('https://entra.example/authorize?x=1'))

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('https://api.example.test/v1/auth/authorize-url')
    expect((init as RequestInit).credentials).toBe('include')
  })

  it('beginLogin throws a friendly error when the backend fails', async () => {
    mockFetch({ detail: 'nope' }, false, 503)
    await expect(beginLogin()).rejects.toThrow(/nope|start sign-in/i)
  })

  it('completeLogin posts code+state with credentials and maps the id token', async () => {
    const fetchMock = mockFetch({ data: { id_token: 'id.jwt' } })

    const tokens = await completeLogin('the-code', 'the-state')

    // tenantId/role are the backend-resolved context (null when the response
    // omits them); Entra does not emit tenant_id/role into the token itself.
    expect(tokens).toEqual({
      idToken: 'id.jwt',
      accessToken: 'id.jwt',
      refreshToken: '',
      tenantId: null,
      role: null,
    })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('https://api.example.test/v1/auth/callback')
    expect((init as RequestInit).credentials).toBe('include')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ code: 'the-code', state: 'the-state' })
  })

  it('completeLogin surfaces the backend error on failure', async () => {
    mockFetch({ detail: 'Sign-in could not be completed.' }, false, 401)
    await expect(completeLogin('c', 's')).rejects.toThrow(/could not be completed/i)
  })

  it('signIn and refreshSession reject — interactive/cookie flows replace them', async () => {
    await expect(signIn()).rejects.toThrow(/interactive/i)
    await expect(refreshSession()).rejects.toThrow(/server-side/i)
  })
})
