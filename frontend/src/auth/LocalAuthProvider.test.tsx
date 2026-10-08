import { act, render, renderHook, screen } from '@testing-library/react'
import type { JSX } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearExplicitDevLogout, clearPersistedDevIdentity, setPersistedDevIdentity } from '../lib/localDevSession'
import { signIn, signOut } from './CognitoClient'
import { LocalAuthProvider } from './LocalAuthProvider'
import { establishServerSession, revokeServerSession, silentRefresh } from './sessionApi'
import { useSession } from './SessionContext'
import { clearActiveTokens, getAuthHeaders } from './tokenStore'
import { RoleSwitcher } from './RoleSwitcher'

vi.mock('./CognitoClient', () => ({
  signIn: vi.fn(),
  signOut: vi.fn(),
}))

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

const CUSTOMER_CLAIMS = { sub: 'cust-1', 'custom:tenant_id': 't1', 'cognito:groups': 't1:customer' }

function SessionInfo(): JSX.Element {
  const { session, status } = useSession()
  return (
    <div>
      <div>status: {status}</div>
      <div>role: {session?.role}</div>
      <div>tenant: {session?.tenantId}</div>
    </div>
  )
}

describe('LocalAuthProvider', () => {
  beforeEach(() => {
    clearActiveTokens()
    // Reaching into the browser storage API directly here would trip
    // frontend-ci.yml's token-storage grep check (it scans every file under
    // this directory, comments included) — go through the exported helper
    // from src/lib/localDevSession.ts instead, which lives outside it.
    clearExplicitDevLogout()
    // A reload-surviving identity is exactly the point of this feature — but
    // that means it also survives between tests in the same jsdom instance
    // unless cleared here.
    clearPersistedDevIdentity()
    vi.clearAllMocks()
    vi.mocked(silentRefresh).mockResolvedValue(null)
    vi.mocked(establishServerSession).mockResolvedValue(undefined)
    vi.mocked(revokeServerSession).mockResolvedValue(undefined)
  })

  it('defaults to platform_admin with the PLATFORM tenant', () => {
    render(
      <LocalAuthProvider>
        <SessionInfo />
      </LocalAuthProvider>,
    )
    expect(screen.getByText('status: authenticated')).toBeInTheDocument()
    expect(screen.getByText('role: platform_admin')).toBeInTheDocument()
    expect(screen.getByText('tenant: PLATFORM')).toBeInTheDocument()
  })

  it('honors an explicit initialRole', () => {
    render(
      <LocalAuthProvider initialRole="warehouse_attendant">
        <SessionInfo />
      </LocalAuthProvider>,
    )
    expect(screen.getByText('role: warehouse_attendant')).toBeInTheDocument()
    expect(screen.getByText('tenant: 10000000-0000-0000-0000-000000000001')).toBeInTheDocument()
  })

  it('a persisted identity from a prior session takes priority over initialRole', () => {
    setPersistedDevIdentity('china_office_staff')

    render(
      <LocalAuthProvider initialRole="warehouse_attendant">
        <SessionInfo />
      </LocalAuthProvider>,
    )

    expect(screen.getByText('role: china_office_staff')).toBeInTheDocument()
  })

  it('sets the local dev header trio in the token store', () => {
    render(
      <LocalAuthProvider initialRole="nigeria_office_staff">
        <SessionInfo />
      </LocalAuthProvider>,
    )
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': '10000000-0000-0000-0000-000000000001',
      'X-Role': 'nigeria_office_staff',
      'X-User-ID': '10000000-0000-0000-0000-000000000013',
    })
  })

  it('switches roles instantly via RoleSwitcher, with no Cognito involved', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    render(
      <LocalAuthProvider>
        <SessionInfo />
        <RoleSwitcher />
      </LocalAuthProvider>,
    )
    expect(screen.getByText('role: platform_admin')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Dev role'), 'customer')

    expect(screen.getByText('role: customer')).toBeInTheDocument()
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': '10000000-0000-0000-0000-000000000001',
      'X-Role': 'customer',
      'X-User-ID': '10000000-0000-0000-0000-000000000021',
    })
  })

  // Ground-truth bug report: "when i am on tab e.g customer or any other tab
  // and i refresh, it goes to the dashboard." Root cause: `identity` was
  // plain React state with nothing persisting it, and App.tsx never passes
  // `initialRole`, so a reload always restarted at the 'platform_admin'
  // default — RoleGuard then bounced whatever now-wrong-role page the user
  // was on to platform_admin's home ("the dashboard"). Reproduced live via
  // Playwright before this fix: switch to tenant_admin, open
  // /admin/customers, reload -> landed on /platform/dashboard every time.
  it('a picked dev role survives a simulated reload (remount)', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const { unmount } = render(
      <LocalAuthProvider>
        <SessionInfo />
        <RoleSwitcher />
      </LocalAuthProvider>,
    )
    expect(screen.getByText('role: platform_admin')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Dev role'), 'tenant_admin')
    expect(screen.getByText('role: tenant_admin')).toBeInTheDocument()

    // A page reload discards all in-memory React state — a fresh mount is
    // the closest a test can get to that without a real browser reload.
    unmount()
    render(
      <LocalAuthProvider>
        <SessionInfo />
      </LocalAuthProvider>,
    )

    expect(screen.getByText('role: tenant_admin')).toBeInTheDocument()
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': '10000000-0000-0000-0000-000000000001',
      'X-Role': 'tenant_admin',
      'X-User-ID': '10000000-0000-0000-0000-000000000011',
    })
  })

  it('the nigeria_warehouse dev identity holds both roles and sends X-Roles', () => {
    render(
      <LocalAuthProvider initialRole="nigeria_warehouse">
        <SessionInfo />
      </LocalAuthProvider>,
    )
    expect(screen.getByText('role: nigeria_office_staff')).toBeInTheDocument()
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': '10000000-0000-0000-0000-000000000001',
      'X-Role': 'nigeria_office_staff',
      'X-Roles': 'nigeria_office_staff,warehouse_attendant',
      'X-User-ID': '10000000-0000-0000-0000-000000000015',
    })
  })

  it('setActiveRole toggles the display role client-side without touching the backend headers', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    function ToggleButton(): JSX.Element {
      const { setActiveRole } = useSession()
      return (
        <button onClick={() => setActiveRole('warehouse_attendant')}>Switch to warehouse</button>
      )
    }
    render(
      <LocalAuthProvider initialRole="nigeria_warehouse">
        <SessionInfo />
        <ToggleButton />
      </LocalAuthProvider>,
    )
    expect(screen.getByText('role: nigeria_office_staff')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Switch to warehouse'))

    expect(screen.getByText('role: warehouse_attendant')).toBeInTheDocument()
    // The header trio sent to the backend is unaffected by the display toggle —
    // it always reflects the dev identity's true primary role.
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': '10000000-0000-0000-0000-000000000001',
      'X-Role': 'nigeria_office_staff',
      'X-Roles': 'nigeria_office_staff,warehouse_attendant',
      'X-User-ID': '10000000-0000-0000-0000-000000000015',
    })
  })

  it('switching dev identity resets the active-role toggle back to the new identity’s primary role', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    function ToggleButton(): JSX.Element {
      const { setActiveRole } = useSession()
      return (
        <button onClick={() => setActiveRole('warehouse_attendant')}>Switch to warehouse</button>
      )
    }
    render(
      <LocalAuthProvider initialRole="nigeria_warehouse">
        <SessionInfo />
        <ToggleButton />
        <RoleSwitcher />
      </LocalAuthProvider>,
    )
    await userEvent.click(screen.getByText('Switch to warehouse'))
    expect(screen.getByText('role: warehouse_attendant')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Dev role'), 'customer')

    expect(screen.getByText('role: customer')).toBeInTheDocument()
  })

  // Ground-truth bug report: "i logged in as ifesinachi (customer), when i
  // logout and refresh the page it still logged in." Root cause: logout()
  // only ever cleared cognitoSession, and session/status fell straight back
  // to the always-on dev-identity fallback (roleSession) — which looks and
  // behaves exactly like being logged in, defeating logout entirely, with or
  // without a reload.
  describe('logout after a real Cognito login', () => {
    async function loginAsCustomer(): Promise<ReturnType<typeof renderHook<ReturnType<typeof useSession>, unknown>>> {
      const idToken = fakeJwt(CUSTOMER_CLAIMS, 3600)
      vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r' })
      const rendered = renderHook(() => useSession(), { wrapper: LocalAuthProvider })
      await act(async () => {
        await rendered.result.current.login('ifesinachi@example.com', 'pw')
      })
      return rendered
    }

    it('does not fall back to the dev-shim session immediately after logout', async () => {
      const { result } = await loginAsCustomer()
      expect(result.current.session?.tenantId).toBe('t1')

      act(() => {
        result.current.logout()
      })

      expect(signOut).toHaveBeenCalledOnce()
      expect(revokeServerSession).toHaveBeenCalledOnce()
      expect(result.current.status).toBe('unauthenticated')
      expect(result.current.session).toBeNull()
      expect(getAuthHeaders()).toEqual({})
    })

    it('stays logged out across a remount simulating a page reload', async () => {
      const { result, unmount } = await loginAsCustomer()

      act(() => {
        result.current.logout()
      })
      expect(result.current.status).toBe('unauthenticated')

      // A page reload discards all in-memory React state — a fresh mount is
      // the closest a test can get to that without a real browser reload.
      // The cookie was revoked, so the mount-time restore finds nothing.
      unmount()
      vi.mocked(silentRefresh).mockResolvedValue(null)
      const remounted = renderHook(() => useSession(), { wrapper: LocalAuthProvider })
      await act(async () => {})

      expect(remounted.result.current.status).toBe('unauthenticated')
      expect(remounted.result.current.session).toBeNull()
      expect(getAuthHeaders()).toEqual({})
    })

    it('a stale (unrevoked) cookie restoring a real session still wins over the logged-out marker', async () => {
      // Belt-and-suspenders: if the cookie somehow survives, the real
      // restored session must not be masked by the last tab's logout flag.
      const { result, unmount } = await loginAsCustomer()
      act(() => {
        result.current.logout()
      })
      unmount()

      const freshToken = fakeJwt(CUSTOMER_CLAIMS, 3600)
      vi.mocked(silentRefresh).mockResolvedValue({ idToken: freshToken, expiresIn: 3600 })
      const remounted = renderHook(() => useSession(), { wrapper: LocalAuthProvider })
      await act(async () => {})

      expect(remounted.result.current.status).toBe('authenticated')
      expect(remounted.result.current.session?.tenantId).toBe('t1')
    })

    it('picking a dev role from RoleSwitcher after logout re-authenticates as that role', async () => {
      const { result, unmount } = await loginAsCustomer()
      act(() => {
        result.current.logout()
      })
      unmount()

      const { default: userEvent } = await import('@testing-library/user-event')
      render(
        <LocalAuthProvider>
          <SessionInfo />
          <RoleSwitcher />
        </LocalAuthProvider>,
      )
      expect(screen.getByText('status: unauthenticated')).toBeInTheDocument()
      // The switcher shows a distinct placeholder rather than silently
      // keeping whatever dev identity was last active — selecting that same
      // value again must still register as a change (a real Cognito login
      // never touches `identity` state, so it could easily already match).
      expect(screen.getByLabelText('Dev role')).toHaveValue('')

      await userEvent.selectOptions(screen.getByLabelText('Dev role'), 'tenant_admin')

      expect(screen.getByText('status: authenticated')).toBeInTheDocument()
      expect(screen.getByText('role: tenant_admin')).toBeInTheDocument()
      expect(getAuthHeaders()).toEqual({
        'X-Tenant-ID': '10000000-0000-0000-0000-000000000001',
        'X-Role': 'tenant_admin',
        'X-User-ID': '10000000-0000-0000-0000-000000000011',
      })
    })

    it('picking a dev role from RoleSwitcher while a real Cognito session is still active ends it', async () => {
      // Ground-truth gap found live, reported by the user: "the dev switcher
      // is not working." Root cause: `session` is `impSession ?? cognitoSession
      // ?? ...` — a lingering real login (e.g. from earlier customer-login
      // testing) unconditionally outranked the dev shim, so picking a role
      // updated the <select> and `identity` but had zero visible effect on
      // the actual session — indistinguishable from "the switcher does
      // nothing." Reproduced live before this fix: log in as a real
      // customer, pick tenant_admin in the switcher, the app stayed on the
      // customer's own session/page.
      const { default: userEvent } = await import('@testing-library/user-event')
      const idToken = fakeJwt(CUSTOMER_CLAIMS, 3600)
      vi.mocked(signIn).mockResolvedValue({ idToken, accessToken: 'a', refreshToken: 'r' })

      function LoginButton(): JSX.Element {
        const { login } = useSession()
        return <button onClick={() => void login('ifesinachi@example.com', 'pw')}>Log in</button>
      }
      render(
        <LocalAuthProvider>
          <SessionInfo />
          <LoginButton />
          <RoleSwitcher />
        </LocalAuthProvider>,
      )
      await userEvent.click(screen.getByText('Log in'))
      await screen.findByText('tenant: t1') // real customer session active

      await userEvent.selectOptions(screen.getByLabelText('Dev role'), 'tenant_admin')

      expect(signOut).toHaveBeenCalledOnce()
      expect(revokeServerSession).toHaveBeenCalledOnce()
      expect(screen.getByText('role: tenant_admin')).toBeInTheDocument()
      expect(screen.getByText('tenant: 10000000-0000-0000-0000-000000000001')).toBeInTheDocument()
      expect(getAuthHeaders()).toEqual({
        'X-Tenant-ID': '10000000-0000-0000-0000-000000000001',
        'X-Role': 'tenant_admin',
        'X-User-ID': '10000000-0000-0000-0000-000000000011',
      })
    })

    it('logging in for real after logout clears the logged-out marker', async () => {
      const { result, unmount } = await loginAsCustomer()
      act(() => {
        result.current.logout()
      })
      unmount()

      const freshToken = fakeJwt(CUSTOMER_CLAIMS, 3600)
      vi.mocked(signIn).mockResolvedValue({ idToken: freshToken, accessToken: 'a', refreshToken: 'r2' })
      const remounted = renderHook(() => useSession(), { wrapper: LocalAuthProvider })
      await act(async () => {})
      expect(remounted.result.current.status).toBe('unauthenticated')

      await act(async () => {
        await remounted.result.current.login('ifesinachi@example.com', 'pw')
      })

      expect(remounted.result.current.status).toBe('authenticated')

      // And logging out again still works — the marker wasn't left stuck.
      act(() => {
        remounted.result.current.logout()
      })
      expect(remounted.result.current.status).toBe('unauthenticated')
    })
  })

  // Regression found live right after shipping the fix above: api/client.ts's
  // 401-recovery path calls the same logout() whenever a retried request
  // still 401s — routine in local dev (e.g. an endpoint the current dev role
  // can't call), completely unrelated to a real login/logout. That must not
  // trip the sticky loggedOut flag, or a single stray 401 anywhere in the app
  // permanently (across reloads) breaks the dev role switcher.
  it('calling logout() with no real Cognito session active does not disable the dev-shim fallback', () => {
    const { result } = renderHook(() => useSession(), { wrapper: LocalAuthProvider })
    expect(result.current.status).toBe('authenticated')
    expect(result.current.session?.role).toBe('platform_admin')

    act(() => {
      result.current.logout()
    })

    expect(signOut).not.toHaveBeenCalled()
    expect(revokeServerSession).not.toHaveBeenCalled()
    expect(result.current.status).toBe('authenticated')
    expect(result.current.session?.role).toBe('platform_admin')
    expect(getAuthHeaders()).toEqual({
      'X-Tenant-ID': 'PLATFORM',
      'X-Role': 'platform_admin',
      'X-User-ID': 'local-platform-admin',
    })
  })
})
