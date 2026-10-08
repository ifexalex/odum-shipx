/**
 * Cross-tenant cache isolation test (Task 09 / Task 11).
 *
 * This is the highest-value test in the suite: it verifies that no tenant A
 * data remains in the TanStack Query cache after a session switch to tenant B.
 * A failure here would mean stale data from one tenant is visible to another
 * after an impersonation exit or login switch — a visible cross-tenant data
 * leak even if the API itself is correctly isolated.
 *
 * Spec reference: 09_state_management_and_data_fetching.md
 *   "queryClient.clear() is called on every tenant-context switch
 *    (login, logout, impersonation enter, impersonation exit)"
 *
 * How it works:
 * 1. Wire App.tsx's onSessionChange → queryClient.clear() pattern directly
 *    by rendering a SessionProvider with the same callback as production.
 * 2. Pre-populate the QueryClient with dummy "tenant A" cache entries.
 * 3. Trigger a session change (logout, which calls onSessionChange(null)).
 * 4. Assert the cache is completely empty — no tenant A data survives.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { signIn, signOut } from '../auth/CognitoClient'
import { useSession } from '../auth/SessionContext'
import { SessionProvider } from '../auth/SessionProvider'
import * as keys from '../api/keys'

vi.mock('../auth/CognitoClient')
// This suite only cares about query-cache clearing on session transitions —
// mock the httpOnly-cookie session-persistence calls so login()/logout()
// don't make real network requests to VITE_API_BASE_URL during a unit test.
vi.mock('../auth/sessionApi', () => ({
  establishServerSession: vi.fn().mockResolvedValue(undefined),
  silentRefresh: vi.fn().mockResolvedValue(null),
  revokeServerSession: vi.fn().mockResolvedValue(undefined),
}))

function fakeJwt(claims: Record<string, unknown>, expiresInSeconds: number): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(
    JSON.stringify({ ...claims, exp: Math.floor(Date.now() / 1000) + expiresInSeconds, iat: Math.floor(Date.now() / 1000) }),
  )
  return `${header}.${payload}.sig`
}

const TENANT_A_CLAIMS = { sub: 'admin-a', 'custom:tenant_id': 'tenant-a', 'cognito:groups': 'tenant-a:tenant_admin' }

let queryClient: QueryClient

// Mirrors App.tsx's production wiring: onSessionChange → queryClient.clear().
function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider onSessionChange={() => queryClient.clear()}>{children}</SessionProvider>
    </QueryClientProvider>
  )
}

describe('Cross-tenant cache isolation', () => {
  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(signOut).mockImplementation(() => {})
  })

  afterEach(() => {
    queryClient.clear()
    vi.clearAllMocks()
  })

  it('clears all cache entries on logout', async () => {
    vi.mocked(signIn).mockResolvedValue({
      idToken: fakeJwt(TENANT_A_CLAIMS, 3600),
      accessToken: 'a',
      refreshToken: 'r1',
    })

    const { result } = renderHook(() => useSession(), { wrapper })

    // Login as tenant A
    await act(async () => {
      await result.current.login('admin-a@acme.com', 'pw')
    })

    // Simulate cached data for tenant A (as the real app would accumulate)
    queryClient.setQueryData(['containers', 'list', {}], { data: [{ id: 'c1', tenant_id: 'tenant-a' }] })
    queryClient.setQueryData(['billing', 'list', {}], { data: [{ id: 'b1', tenant_id: 'tenant-a' }] })
    queryClient.setQueryData(['customers', 'list', {}], { data: [{ id: 'cust1', tenant_id: 'tenant-a' }] })

    expect(queryClient.getQueriesData({ queryKey: [] })).toHaveLength(3)

    // Logout → onSessionChange(null) → queryClient.clear()
    act(() => { result.current.logout() })

    // Every cache entry must be gone — no tenant A data survives
    expect(queryClient.getQueriesData({ queryKey: [] })).toHaveLength(0)
  })

  it('clears cache on impersonation start (entering tenant A as platform admin)', async () => {
    vi.mocked(signIn).mockResolvedValue({
      idToken: fakeJwt({ sub: 'platform-1', 'custom:tenant_id': 'PLATFORM', 'cognito:groups': 'platform_admin' }, 3600),
      accessToken: 'a',
      refreshToken: 'r1',
    })

    const { result } = renderHook(() => useSession(), { wrapper })

    await act(async () => {
      await result.current.login('platform@shipx.co', 'pw')
    })

    // Platform admin has some cached platform-level data
    queryClient.setQueryData(['platform-tenants', 'list'], { data: [{ id: 'tenant-a' }, { id: 'tenant-b' }] })
    expect(queryClient.getQueriesData({ queryKey: [] })).toHaveLength(1)

    // Start impersonating tenant A — session switches, cache must clear
    act(() => {
      result.current.startImpersonation(fakeJwt(TENANT_A_CLAIMS, 1800), 'Acme Logistics')
    })

    expect(queryClient.getQueriesData({ queryKey: [] })).toHaveLength(0)
  })

  it('clears cache on impersonation exit (returning from tenant A to platform admin)', async () => {
    vi.mocked(signIn).mockResolvedValue({
      idToken: fakeJwt({ sub: 'platform-1', 'custom:tenant_id': 'PLATFORM', 'cognito:groups': 'platform_admin' }, 3600),
      accessToken: 'a',
      refreshToken: 'r1',
    })

    const { result } = renderHook(() => useSession(), { wrapper })

    await act(async () => {
      await result.current.login('platform@shipx.co', 'pw')
    })

    act(() => {
      result.current.startImpersonation(fakeJwt(TENANT_A_CLAIMS, 1800), 'Acme Logistics')
    })

    // Impersonation session accumulates tenant A data in cache
    queryClient.setQueryData(['containers', 'list', {}], { data: [{ id: 'c1', tenant_id: 'tenant-a' }] })
    queryClient.setQueryData(['billing', 'list', {}], { data: [{ id: 'b1', tenant_id: 'tenant-a' }] })
    expect(queryClient.getQueriesData({ queryKey: [] })).toHaveLength(2)

    // Exit impersonation — must wipe all tenant A data
    act(() => { result.current.exitImpersonation() })

    expect(queryClient.getQueriesData({ queryKey: [] })).toHaveLength(0)
  })

  it('never stores tenantId inside any query key', () => {
    // Regression guard: verify that no query key in the key factories contains
    // a UUID-shaped tenant ID — this enforces the "no tenantId in keys" rule
    // from 09_state_management_and_data_fetching.md.
    const tenantId = '10000000-0000-0000-0000-000000000001'
    const uuidPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/

    const keyList = [
      keys.containerKeys.all,
      keys.containerKeys.list(),
      keys.containerKeys.detail('some-id'),
      keys.billingKeys.all,
      keys.billingKeys.list(),
      keys.claimKeys.all,
      keys.staffKeys.all,
      keys.configKeys.all,
    ]

    for (const key of keyList) {
      const serialized = JSON.stringify(key)
      expect(serialized).not.toContain(tenantId)
      // Guard against any UUID pattern — catches future regressions
      expect(serialized).not.toMatch(uuidPattern)
    }
  })
})
