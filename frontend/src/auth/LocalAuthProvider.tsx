import { useEffect, useRef, useState, type JSX, type ReactNode } from 'react'
import {
  clearExplicitDevLogout,
  getPersistedDevIdentity,
  hasExplicitDevLogout,
  setExplicitDevLogout,
  setPersistedDevIdentity,
} from '../lib/localDevSession'
import { signIn as cognitoSignIn, signOut as cognitoSignOut } from './CognitoClient'
import { sessionFromIdToken } from './jwt'
import { LocalRoleContext, type DevIdentityKey } from './LocalRoleContext'
import { establishServerSession, revokeServerSession, silentRefresh } from './sessionApi'
import { SessionContext, type SessionStatus } from './SessionContext'
import { useRegisterSessionActions } from './sessionBridge'
import { clearActiveTokens, setActiveLocalAuth, setActiveTokens } from './tokenStore'
import type { Session, UserRole } from './types'

// Same 80%-of-lifetime refresh margin SessionProvider uses.
const REFRESH_SAFETY_MARGIN = 0.8

export interface LocalAuthProviderProps {
  children: ReactNode
  initialRole?: DevIdentityKey
}

// Fixed UUID matching the Acme Shipping Ltd dev-seed tenant. seed.py always
// inserts this tenant with this exact UUID so it survives make stack resets.
const DEMO_TENANT_ID = '10000000-0000-0000-0000-000000000001'

// The real seeded tenant_user UUIDs from scripts/seed.py, not placeholder
// slugs. In production session.userId is the Cognito sub, which equals
// tenant_user.id for seeded users — so any UI rule comparing the session user
// against a record's created_by (self-approval, "created by me" filters) only
// behaves correctly when the shim supplies the same shape. With slugs those
// comparisons silently never matched, hiding the bug they exist to catch.
// These ids are fixed across `make stack`, which is why seed.py pins them.
const ROLE_USER_IDS: Record<DevIdentityKey, string> = {
  platform_admin: 'local-platform-admin', // no tenant_user row exists by design
  tenant_admin: '10000000-0000-0000-0000-000000000011',
  china_office_staff: '10000000-0000-0000-0000-000000000012',
  nigeria_office_staff: '10000000-0000-0000-0000-000000000013',
  warehouse_attendant: '10000000-0000-0000-0000-000000000014',
  customer: '10000000-0000-0000-0000-000000000021',
  nigeria_warehouse: '10000000-0000-0000-0000-000000000015',
}

// Matches the names in scripts/bootstrap_local.sh / scripts/seed.py so the
// dev role-switcher shows the same names the seeded Cognito users would have.
const ROLE_NAMES: Record<DevIdentityKey, string> = {
  platform_admin: 'Platform Admin',
  tenant_admin: 'Chidi Okafor',
  china_office_staff: 'Li Wei',
  nigeria_office_staff: 'Emeka Eze',
  warehouse_attendant: 'Tunde Bello',
  customer: 'Chioma Eze',
  nigeria_warehouse: 'Ngozi Adeyemi (Nigeria + Warehouse)',
}

// Every role each dev identity holds — primary role is always roles[0].
// 'nigeria_warehouse' is the one multi-role identity, mirroring the real
// multi-role Acme seed user (scripts/seed.py) so the role-switch toggle can
// be exercised locally without needing a real Cognito login.
const IDENTITY_ROLES: Record<DevIdentityKey, UserRole[]> = {
  platform_admin: ['platform_admin'],
  tenant_admin: ['tenant_admin'],
  china_office_staff: ['china_office_staff'],
  nigeria_office_staff: ['nigeria_office_staff'],
  warehouse_attendant: ['warehouse_attendant'],
  customer: ['customer'],
  nigeria_warehouse: ['nigeria_office_staff', 'warehouse_attendant'],
}

function sessionForIdentity(identity: DevIdentityKey): Session {
  const roles = IDENTITY_ROLES[identity]
  const primary = roles[0]!
  const tenantId = primary === 'platform_admin' ? 'PLATFORM' : DEMO_TENANT_ID
  return {
    tenantId,
    tenantName: null,
    userId: ROLE_USER_IDS[identity],
    name: ROLE_NAMES[identity],
    role: primary,
    roles,
    isPlatformAdmin: tenantId === 'PLATFORM',
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 24 * 60 * 60 * 1000,
    tokenType: 'cognito',
  }
}

// Dev-only shim for scripts/local_server.py's X-Tenant-ID/X-Role/X-Roles/X-User-ID
// header auth — skips Cognito entirely so the 7 dev identities can be flipped
// instantly via RoleSwitcher without needing real Cognito users. Sets the
// same Session shape SessionProvider does, so no other code needs to know
// it's running against the shim. Gate this behind import.meta.env.DEV at the
// call site — never ship it in the production bundle.
//
// Impersonation is supported: the backend impersonate endpoint mints a real
// HS256 token even under header auth, and local_server.py maps its claims the
// same way the production REQUEST authorizer does — so "View as tenant" on
// the platform tenant detail works identically in both auth modes.
export function LocalAuthProvider({ children, initialRole = 'platform_admin' }: LocalAuthProviderProps): JSX.Element {
  // Ground-truth gap found live: "when i am on tab e.g customer or any other
  // tab and i refresh, it goes to the dashboard." A reload previously always
  // restarted this at `initialRole` (App.tsx never passes one, so always
  // 'platform_admin'), discarding whatever role RoleSwitcher had active —
  // RoleGuard then bounced the now-wrong-role session to that role's home
  // page. Restoring the last-picked identity here, before anything else
  // reads `identity`, is what makes a reload land back on the same page
  // instead. Persisted via localDevSession.ts (browser storage, kept
  // outside src/auth/ — see that file for why) rather than plain React
  // state, which cannot survive a reload at all.
  const [identity, setIdentityState] = useState<DevIdentityKey>(() => getPersistedDevIdentity() ?? initialRole)
  // Client-side-only active/display role override — independent of `identity`.
  // Reset to null (falls back to the identity's primary role) whenever the
  // dev identity itself changes, since that's a different "user" logging in.
  const [activeRoleOverride, setActiveRoleOverride] = useState<UserRole | null>(null)
  const [impSession, setImpSession] = useState<Session | null>(null)
  // A real Cognito login (e.g. a customer who claimed their invite and signed
  // in with email + password on /login) against Moto — the dev-role switcher
  // below is a *shim for staff roles*, not a blanket replacement for real
  // auth, so this overlays it whenever a genuine login has happened.
  const [cognitoSession, setCognitoSession] = useState<Session | null>(null)
  // Set once the user explicitly logs out of a real Cognito session — see
  // src/lib/localDevSession.ts for why this lives outside src/auth/ and why
  // it exists at all: without it, the dev-identity fallback below
  // unconditionally resurfaces the instant cognitoSession clears, silently
  // "logging back in" as the dev shim — including across a page reload,
  // since plain React state can't survive one but this flag does.
  const [loggedOut, setLoggedOut] = useState(() => hasExplicitDevLogout())
  const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const identitySession = sessionForIdentity(identity)
  const roleSession: Session =
    activeRoleOverride && identitySession.roles.includes(activeRoleOverride)
      ? { ...identitySession, role: activeRoleOverride }
      : identitySession
  const session = impSession ?? cognitoSession ?? (loggedOut ? null : roleSession)

  // Shared by logout() and setIdentity() below — ends whatever real Cognito
  // session is active (token, timers, server-side revoke). Callers decide
  // what happens to `loggedOut`/`identity` afterward; this only ever touches
  // the Cognito side.
  function endCognitoSession(): void {
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    refreshTimer.current = null
    cognitoSignOut()
    setCognitoSession(null)
    void revokeServerSession()
    clearActiveTokens()
  }

  function setIdentity(next: DevIdentityKey): void {
    // Ground-truth gap found live, reported by the user ("the dev switcher
    // is not working"): `session` is `impSession ?? cognitoSession ?? ...` —
    // a real Cognito session (e.g. left over from testing a real customer
    // login earlier) unconditionally outranks the dev shim, so picking a
    // role here updated the <select> and `identity` but had *zero* visible
    // effect on the actual session/page, with nothing telling the developer
    // why. Reproduced live: log in as a real customer, pick tenant_admin in
    // the switcher, the app stays on the customer's own page. Picking a dev
    // role is an unambiguous "use the shim now" signal, so it must be able
    // to end a real session standing in its way, not just get silently
    // outranked by one.
    if (cognitoSession) endCognitoSession()
    setActiveRoleOverride(null)
    setIdentityState(next)
    setPersistedDevIdentity(next)
    // Explicitly picking a dev role is as much an "I want to be logged in as
    // this identity" action as a real login — it must be able to escape a
    // prior explicit logout, or the switcher would look broken right after
    // clicking "Log out" once.
    setLoggedOut(false)
    clearExplicitDevLogout()
  }

  useEffect(() => {
    // While impersonating, genuinely logged in as a real Cognito user (e.g. a
    // customer who claimed their invite), or explicitly logged out, don't
    // (re-)establish the local dev header trio — the first two because the
    // Bearer token owns auth, the third because re-sending headers here is
    // exactly what silently resurrected a session immediately after logout().
    if (impSession || cognitoSession || loggedOut) return
    // Always the identity's true primary role/roles — never the display-only
    // activeRoleOverride, so the toggle has zero effect on what the backend sees.
    setActiveLocalAuth({
      tenantId: identitySession.tenantId,
      role: identitySession.role,
      roles: identitySession.roles,
      userId: identitySession.userId,
    })
    // identitySession is fully determined by `identity` — depend on that
    // directly rather than the freshly-allocated object/array each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [impSession, cognitoSession, loggedOut, identity])

  function scheduleCognitoRefresh(next: Session): void {
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    const delay = (next.expiresAt - Date.now()) * REFRESH_SAFETY_MARGIN
    if (delay <= 0) return
    refreshTimer.current = setTimeout(() => {
      void restoreCognitoFromCookie()
    }, delay)
  }

  // Mirrors SessionProvider.restoreFromCookie — exchanges the httpOnly
  // refresh-token cookie for a fresh ID token so a real (non-dev-identity)
  // login survives a page reload here too.
  async function restoreCognitoFromCookie(): Promise<boolean> {
    const tokens = await silentRefresh()
    if (!tokens) return false
    const next = sessionFromIdToken(tokens.idToken)
    setActiveTokens({ idToken: tokens.idToken, tokenType: 'cognito' })
    setCognitoSession(next)
    // A genuinely restored session is authoritative over any stale explicit-
    // logout marker (there shouldn't be one — logout() revokes the cookie
    // this reads — but a real session must never stay masked by it).
    setLoggedOut(false)
    clearExplicitDevLogout()
    scheduleCognitoRefresh(next)
    return true
  }

  useEffect(() => {
    void restoreCognitoFromCookie()
    // Mount-only — a real login's cookie, if any, should be picked up once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Ground-truth gap found live: this was hardcoded to 'authenticated', so
  // RoleGuard (status !== 'authenticated' || !session -> /login) could never
  // treat this provider as logged out, no matter what session held. Deriving
  // it from `session` is what makes an explicit logout actually reach the
  // login screen instead of silently falling through to the dev shim.
  const status: SessionStatus = session ? 'authenticated' : 'unauthenticated'

  async function login(email: string, password: string): Promise<Session> {
    const tokens = await cognitoSignIn(email, password)
    const next = sessionFromIdToken(tokens.idToken)
    setActiveTokens({ idToken: tokens.idToken, tokenType: 'cognito' })
    setCognitoSession(next)
    setLoggedOut(false)
    clearExplicitDevLogout()
    scheduleCognitoRefresh(next)
    // Best-effort, matches SessionProvider.login — a failure here only costs
    // reload persistence, not the login itself.
    void establishServerSession(tokens.refreshToken).catch((err: unknown) => {
      console.warn('Failed to persist session for reload — will not survive a page refresh', err)
    })
    return next
  }

  function logout(): void {
    // Regression found live right after shipping the real-logout fix this
    // function otherwise implements: the API client's 401-recovery path
    // (api/client.ts's recoverFrom401) calls this same logout() whenever a
    // retried request still 401s — routine in local dev (e.g. an endpoint
    // the current dev role can't call), completely unrelated to any real
    // login/logout. With no real Cognito session to end, this must be a true
    // no-op — not just skip the sticky loggedOut flag below, but leave
    // tokenStore untouched too, or clearActiveTokens() blanks the active dev
    // header trio with no state change left to trigger the effect below that
    // would otherwise restore it, until some unrelated re-render happens to.
    if (!cognitoSession) return

    endCognitoSession()
    // Ground-truth gap found live: without this, clearing cognitoSession
    // above just revealed the dev-identity fallback (session/status derived
    // from it above) as if the user had never logged out at all — and that
    // fallback re-derives from `identity` state, which doesn't reset itself,
    // so it survived a page reload too. Persisted via localDevSession so the
    // "logged out" state itself survives the reload the bug report was about.
    setLoggedOut(true)
    setExplicitDevLogout()
  }

  const refreshNow = async (): Promise<void> => undefined

  function exitImpersonation(): void {
    if (expiryTimer.current) clearTimeout(expiryTimer.current)
    expiryTimer.current = null
    setImpSession(null)
    setActiveLocalAuth({
      tenantId: identitySession.tenantId,
      role: identitySession.role,
      roles: identitySession.roles,
      userId: identitySession.userId,
    })
  }

  function startImpersonation(idToken: string, tenantName?: string): void {
    const built = sessionFromIdToken(idToken)
    if (tenantName) built.tenantName = tenantName
    setActiveTokens({ idToken, tokenType: 'impersonation' })
    setImpSession(built)
    setLoggedOut(false)
    clearExplicitDevLogout()

    // Impersonation tokens hard-expire (30 min server-side) — drop back to
    // the role-switcher session when that happens rather than 401-looping.
    const delay = built.expiresAt - Date.now()
    if (expiryTimer.current) clearTimeout(expiryTimer.current)
    if (delay > 0) expiryTimer.current = setTimeout(exitImpersonation, delay)
  }

  // Client-side-only active-role toggle — never touches the token/headers.
  function setActiveRole(role: UserRole): void {
    if (!identitySession.roles.includes(role)) return
    setActiveRoleOverride(role)
  }

  useRegisterSessionActions({ refreshNow, logout, exitImpersonation })

  return (
    <SessionContext.Provider
      value={{
        session,
        status,
        login,
        logout,
        startImpersonation,
        exitImpersonation,
        refreshNow,
        setActiveRole,
      }}
    >
      <LocalRoleContext.Provider value={{ identity, setIdentity }}>{children}</LocalRoleContext.Provider>
    </SessionContext.Provider>
  )
}
