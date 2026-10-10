import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { refreshSession, signIn, signOut } from './EntraClient'

describe('EntraClient (ROPC)', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_ENTRA_TOKEN_ENDPOINT', 'https://t.ciamlogin.com/t.onmicrosoft.com/oauth2/v2.0/token')
    vi.stubEnv('VITE_ENTRA_CLIENT_ID', 'client-123')
    vi.stubEnv('VITE_ENTRA_SCOPE', 'openid profile offline_access')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    signOut()
  })

  function mockTokenResponse(body: Record<string, unknown>, ok = true): void {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok,
        json: () => Promise.resolve(body),
      }),
    )
  }

  it('signIn posts the ROPC password grant and maps the tokens', async () => {
    mockTokenResponse({ id_token: 'id.jwt', access_token: 'acc', refresh_token: 'ref' })

    const tokens = await signIn('user@x.com', 'pw')

    expect(tokens).toEqual({ idToken: 'id.jwt', accessToken: 'acc', refreshToken: 'ref' })
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    const call = fetchMock.mock.calls[0]!
    const url = call[0] as string
    const init = call[1] as { body: string }
    expect(url).toContain('/oauth2/v2.0/token')
    const sent = new URLSearchParams(init.body)
    expect(sent.get('grant_type')).toBe('password')
    expect(sent.get('username')).toBe('user@x.com')
    expect(sent.get('password')).toBe('pw')
    expect(sent.get('client_id')).toBe('client-123')
  })

  it('refreshSession uses the refresh_token grant', async () => {
    mockTokenResponse({ id_token: 'id2', access_token: 'acc2', refresh_token: 'ref2' })

    const tokens = await refreshSession('old-refresh')

    expect(tokens.idToken).toBe('id2')
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    const init = fetchMock.mock.calls[0]![1] as { body: string }
    const sent = new URLSearchParams(init.body)
    expect(sent.get('grant_type')).toBe('refresh_token')
    expect(sent.get('refresh_token')).toBe('old-refresh')
  })

  it('surfaces the Entra error code as the Error name', async () => {
    mockTokenResponse({ error: 'invalid_grant', error_description: 'bad creds' }, false)

    await expect(signIn('user@x.com', 'wrong')).rejects.toMatchObject({
      name: 'invalid_grant',
      message: 'bad creds',
    })
  })
})
