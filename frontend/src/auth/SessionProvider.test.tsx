import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { signIn, signOut } from './authClient'
import { establishServerSession, revokeServerSession, silentRefresh } from './sessionApi'
import { useSession } from './SessionContext'
import { SessionProvider } from './SessionProvider'
import { getAuthHeaders } from './tokenStore'

vi.mock('./authClient', () => ({
  signIn: vi.fn(),
  signOut: vi.fn(),
}))

// The Cognito refresh token never lives in JS memory past the single
// establishServerSession() call at login — silentRefresh() (backed by the
// httpOnly cookie services/auth/handler.py sets) is the only refresh path
// SessionProvider has left; see tokenStore.ts's comment on why there's no
// refreshToken field to mock a value into here.
vi.mock('./sessionApi', () => ({
  establishServerSession: vi.fn(),
  silentRefresh: vi.fn(),
  revokeServerSession: vi.fn(),
}))

function fakeJwt(claims: Record<string, unknown>, expiresInSeconds: number): string {
  const base64url = (input: string): string =>
    btoa(input).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  const exp = Math.floor(Date.now() / 1000) + expiresInSeconds
  const header = base64url(JSON.stringify({ alg: 'none' }))
  const payload = base64url(JSON.stringify({ ...claims, exp }))
  return `${header}.${payload}.signature`
}

const ADMIN_CLAIMS = { sub: 'admin-1', 'custom:tenant_id': 't1', 'cognito:groups': 't1:tenant_admin' }

// Every mount fires the silent-restore effect — settle it (default: no cookie,
// so it resolves to 'unauthenticated', matching a fresh test environment)
// before the test proceeds, the same way a real app waits past SessionLoading.
async function renderSession() {
  const rendered = renderHook(() => useSession(), { wrapper: SessionProvider })
  await act(async () => {})
  return rendered
}

describe('SessionProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(silentRefresh).mockResolvedValue(null)
    vi.mocked(establishServerSession).mockResolvedValue(undefined)
    vi.mocked(revokeServerSession).mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts in "loading" status while the mount-time silent restore is in flight', () => {
    // Deliberately not awaited — this is the synchronous instant right after
    // mount, before any effect has had a chance to run its microtask. Unmount
    // immediately so that microtask (still in flight) finds its effect
    // already cleaned up and never calls setState outside of act().
    const { result, unmount } = renderHook(() => useSession(), { wrapper: SessionProvider })
    expect(result.current.status).toBe('loading')
    unmount()
  })

  it('restores an authenticated session on mount from the httpOnly refresh cookie, with no login() call', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(silentRefresh).mockResolvedValue({ idToken, expiresIn: 3600 })

    const { result } = await renderSession()

    expect(result.current.status).toBe('authenticated')
    expect(result.current.session?.tenantId).toBe('t1')
    expect(getAuthHeaders()).toEqual({ Authorization: `Bearer ${idToken}` })
    expect(signIn).not.toHaveBeenCalled()
  })

  it('settles to "unauthenticated" on mount when there is no valid session cookie to restore', async () => {
    const { result } = await renderSession()
    expect(result.current.status).toBe('unauthenticated')
    expect(result.current.session).toBeNull()
  })

  it('logs in, exposes the parsed session, and sets the auth header', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r' })

    const { result } = await renderSession()
    expect(result.current.status).toBe('unauthenticated')

    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    expect(result.current.status).toBe('authenticated')
    expect(result.current.session?.role).toBe('tenant_admin')
    expect(result.current.session?.tenantId).toBe('t1')
    expect(getAuthHeaders()).toEqual({ Authorization: `Bearer ${idToken}` })
    // The refresh token is handed to the backend to persist as an httpOnly
    // cookie — and never touches any variable this test (or the app) could
    // read back out afterward.
    expect(establishServerSession).toHaveBeenCalledWith('r', 'tenant')
  })

  it('still completes login when persisting the server session fails (current-tab session is not held hostage)', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r' })
    vi.mocked(establishServerSession).mockRejectedValue(new Error('network blip'))
    const { result } = await renderSession()

    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    expect(result.current.status).toBe('authenticated')
  })

  it('keeps status unauthenticated and rethrows on a failed login', async () => {
    vi.mocked(signIn).mockRejectedValue(new Error('Incorrect username or password.'))
    const { result } = await renderSession()

    await act(async () => {
      await expect(result.current.login('admin@acme.com', 'wrong')).rejects.toThrow(
        'Incorrect username or password.',
      )
    })

    expect(result.current.status).toBe('unauthenticated')
    expect(result.current.session).toBeNull()
  })

  it('logs out, clears the auth header, and revokes the server-side session', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    await act(async () => {
      result.current.logout()
    })

    expect(signOut).toHaveBeenCalledOnce()
    expect(revokeServerSession).toHaveBeenCalledOnce()
    expect(result.current.status).toBe('unauthenticated')
    expect(result.current.session).toBeNull()
    expect(getAuthHeaders()).toEqual({})
  })

  it('silently refreshes the session ahead of expiry via the httpOnly cookie', async () => {
    vi.useFakeTimers()
    const idToken = fakeJwt(ADMIN_CLAIMS, 1000)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r1' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    const refreshedToken = fakeJwt(ADMIN_CLAIMS, 1000)
    vi.mocked(silentRefresh).mockResolvedValue({ idToken: refreshedToken, expiresIn: 1000 })

    // Refresh fires at 80% of the 1000s lifetime = 800s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800_000)
    })

    expect(silentRefresh).toHaveBeenCalled()
    expect(getAuthHeaders()).toEqual({ Authorization: `Bearer ${refreshedToken}` })
  })

  it('logs the session out when the scheduled refresh finds the cookie gone (expired/revoked)', async () => {
    vi.useFakeTimers()
    const idToken = fakeJwt(ADMIN_CLAIMS, 1000)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r1' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    vi.mocked(silentRefresh).mockResolvedValue(null)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(800_000)
    })

    expect(result.current.status).toBe('unauthenticated')
    expect(result.current.session).toBeNull()
    expect(getAuthHeaders()).toEqual({})
  })

  it('tags the active token with X-Token-Type while impersonating, and never refreshes it', async () => {
    vi.useFakeTimers()
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r1' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    const impToken = fakeJwt(
      {
        sub: 'tenant-user-1',
        'custom:tenant_id': 'tenant-A',
        'cognito:groups': 'tenant-A:tenant_admin',
        impersonated_by: 'admin-1',
        session_id: 'sess-1',
        read_only: 'true',
      },
      1800,
    )

    act(() => {
      result.current.startImpersonation(impToken)
    })

    expect(result.current.session?.readOnly).toBe(true)
    expect(result.current.session?.tenantId).toBe('tenant-A')
    expect(getAuthHeaders()).toEqual({ Authorization: `Bearer ${impToken}`, 'X-Token-Type': 'impersonation' })

    // Even past the 80%-of-lifetime mark, impersonation tokens must not refresh.
    vi.mocked(silentRefresh).mockClear()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1700_000)
    })
    expect(silentRefresh).not.toHaveBeenCalled()
  })

  it('ignores a manual refreshNow() call while impersonating (not just the scheduled timer)', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r1' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    const impToken = fakeJwt(
      { sub: 'tenant-user-1', 'custom:tenant_id': 'tenant-A', 'cognito:groups': 'tenant-A:tenant_admin' },
      1800,
    )
    act(() => {
      result.current.startImpersonation(impToken)
    })

    vi.mocked(silentRefresh).mockClear()
    await act(async () => {
      await result.current.refreshNow()
    })

    expect(silentRefresh).not.toHaveBeenCalled()
    expect(getAuthHeaders()).toEqual({ Authorization: `Bearer ${impToken}`, 'X-Token-Type': 'impersonation' })
  })

  it('restores the platform admin session on manual exit, with no leaked tenant state', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r1' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    const impToken = fakeJwt(
      { sub: 'tenant-user-1', 'custom:tenant_id': 'tenant-A', 'cognito:groups': 'tenant-A:tenant_admin' },
      1800,
    )
    act(() => {
      result.current.startImpersonation(impToken)
    })
    expect(result.current.session?.tenantId).toBe('tenant-A')

    act(() => {
      result.current.exitImpersonation()
    })

    expect(result.current.session?.tenantId).toBe('t1')
    expect(result.current.session?.role).toBe('tenant_admin')
    expect(getAuthHeaders()).toEqual({ Authorization: `Bearer ${idToken}` })
  })

  it('auto-exits and notifies on the 30-minute impersonation hard expiry', async () => {
    vi.useFakeTimers()
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r1' })
    const onImpersonationExpire = vi.fn()
    const rendered = renderHook(() => useSession(), {
      wrapper: ({ children }) => (
        <SessionProvider onImpersonationExpire={onImpersonationExpire}>{children}</SessionProvider>
      ),
    })
    await act(async () => {})
    const { result } = rendered
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    const impToken = fakeJwt(
      { sub: 'tenant-user-1', 'custom:tenant_id': 'tenant-A', 'cognito:groups': 'tenant-A:tenant_admin' },
      5,
    )
    act(() => {
      result.current.startImpersonation(impToken)
    })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000)
    })

    expect(onImpersonationExpire).toHaveBeenCalledOnce()
    expect(result.current.session?.tenantId).toBe('t1')
  })

  it('fires onSessionChange on every transition for query-cache invalidation (Task 09)', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r1' })
    const onSessionChange = vi.fn()
    const rendered = renderHook(() => useSession(), {
      wrapper: ({ children }) => <SessionProvider onSessionChange={onSessionChange}>{children}</SessionProvider>,
    })
    await act(async () => {})
    const { result } = rendered

    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })
    expect(onSessionChange).toHaveBeenCalledWith(expect.objectContaining({ tenantId: 't1' }))

    act(() => {
      result.current.logout()
    })
    expect(onSessionChange).toHaveBeenLastCalledWith(null)
  })

  it('setActiveRole switches the active/display role client-side with no request and no token change', async () => {
    const MULTI_ROLE_CLAIMS = {
      sub: 'user-1',
      'custom:tenant_id': 't1',
      'cognito:groups': 't1:nigeria_office_staff,t1:warehouse_attendant',
    }
    const idToken = fakeJwt(MULTI_ROLE_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('multi@acme.com', 'pw')
    })
    expect(result.current.session?.role).toBe('nigeria_office_staff')
    // Mount's silent-restore already called this once — clear it so the
    // assertion below is specifically about setActiveRole, not the mount effect.
    vi.mocked(silentRefresh).mockClear()

    act(() => {
      result.current.setActiveRole('warehouse_attendant')
    })

    expect(result.current.session?.role).toBe('warehouse_attendant')
    expect(result.current.session?.roles.sort()).toEqual(['nigeria_office_staff', 'warehouse_attendant'])
    // No new token, no request — same idToken still active.
    expect(getAuthHeaders()).toEqual({ Authorization: `Bearer ${idToken}` })
    expect(silentRefresh).not.toHaveBeenCalled()
  })

  it('setActiveRole is a no-op when the role is not one of the user’s assigned roles', async () => {
    const idToken = fakeJwt(ADMIN_CLAIMS, 3600)
    vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r' })
    const { result } = await renderSession()
    await act(async () => {
      await result.current.login('admin@acme.com', 'pw')
    })

    act(() => {
      result.current.setActiveRole('warehouse_attendant')
    })

    expect(result.current.session?.role).toBe('tenant_admin')
  })
})
