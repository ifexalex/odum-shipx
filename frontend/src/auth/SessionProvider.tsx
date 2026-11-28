import { useEffect, useRef, useState, type JSX, type ReactNode } from 'react'
import { platformApi } from '../api/tenantManagement'
import {
  beginInteractiveLogin,
  completeInteractiveLogin,
  signIn as cognitoSignIn,
  signOut as cognitoSignOut,
  submitMfaCode,
  verifyMfaSetup,
  type CognitoPoolKind,
  type CognitoTokens,
} from './authClient'
import { sessionFromIdToken } from './jwt'
import { establishServerSession, revokeServerSession, silentRefresh } from './sessionApi'
import { SessionContext, type SessionStatus } from './SessionContext'
import { SessionTimeoutModal } from './SessionTimeoutModal'
import { useRegisterSessionActions } from './sessionBridge'
import { clearActiveTokens, getActiveIdToken, getActiveTokenType, setActiveTokens } from './tokenStore'
import type { Session, UserRole } from './types'
import { useIdleTimeout } from './useIdleTimeout'

// Inactivity timeout: warn after this long idle, then hard-logout after the
// warning countdown. Overridable per environment; defaults 30 min + 60 s.
function _positiveEnv(raw: unknown, fallback: number): number {
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : fallback
}
const IDLE_MS = _positiveEnv(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES, 30) * 60_000
const WARNING_MS = _positiveEnv(import.meta.env.VITE_IDLE_WARNING_SECONDS, 60) * 1_000

export interface SessionProviderProps {
  children: ReactNode
  /** Fires on every session transition (login/logout/impersonation start/exit) — wire to queryClient.clear() in Task 09. */
  onSessionChange?: (session: Session | null) => void
  /** Fires when an impersonation session hits its 30-minute hard expiry. */
  onImpersonationExpire?: () => void
}

interface SavedSession {
  session: Session
  idToken: string
}

// Refresh ahead of the actual expiry so a request never races a just-expired
// token — 80% of the token's remaining lifetime from the moment it was issued.
const REFRESH_SAFETY_MARGIN = 0.8

export function SessionProvider({
  children,
  onSessionChange,
  onImpersonationExpire,
}: SessionProviderProps): JSX.Element {
  const [session, setSession] = useState<Session | null>(null)
  // Starts 'loading', not 'unauthenticated' — the mount effect below always
  // attempts a silent restore before anything renders a login screen; see
  // RoleGuard/RootRedirect, which both treat 'loading' as "wait," not "bounce."
  const [status, setStatus] = useState<SessionStatus>('loading')
  // Epoch-ms hard-logout deadline while the inactivity warning is showing; null hides it.
  const [idleDeadline, setIdleDeadline] = useState<number | null>(null)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Saved only while impersonating — the platform admin's own session/idToken, restored on exit.
  const previousRef = useRef<SavedSession | null>(null)
  // Single-flight deduplication so concurrent 401 recoveries share one /v1/auth/refresh call.
  const inFlightRefreshRef = useRef<Promise<void> | null>(null)
  // Track the last identity tuple so routine token refreshes do not wipe React Query cache.
  const lastIdentityRef = useRef<string | null>(null)
  const authChannelRef = useRef<BroadcastChannel | null>(null)

  function clearTimers(): void {
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    if (expiryTimer.current) clearTimeout(expiryTimer.current)
    refreshTimer.current = null
    expiryTimer.current = null
  }

  function applySession(next: Session | null): void {
    setSession(next)
    const nextIdentity = next ? `${next.userId}|${next.tenantId}|${next.readOnly ? 'ro' : 'rw'}` : null
    if (nextIdentity !== lastIdentityRef.current) {
      lastIdentityRef.current = nextIdentity
      onSessionChange?.(next)
    }
  }

  // `function` declarations (not `useCallback` consts) so scheduleRefresh and
  // refreshNow can reference each other regardless of textual order — both
  // are hoisted within this component body.
  function scheduleRefresh(next: Session): void {
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    const delay = (next.expiresAt - Date.now()) * REFRESH_SAFETY_MARGIN
    if (delay <= 0) return
    refreshTimer.current = setTimeout(() => {
      // refreshNow() throws on failure so recoverFrom401's explicit `await`
      // can catch it — but nothing awaits this background/scheduled firing,
      // so an uncaught rejection here would surface as an unhandled promise
      // rejection instead. The failure is already fully handled inside
      // refreshNow() (status/session cleared) before it throws.
      refreshNow().catch(() => undefined)
    }, delay)
  }

  // Exchanges the httpOnly refresh-token cookie (services/auth/handler.py)
  // for a fresh ID token — never a raw Cognito refresh token passed through
  // JS. Used both for the proactive 80%-of-lifetime refresh and for the
  // mount-time silent restore below (same cookie, same call).
  async function restoreFromCookie(): Promise<boolean> {
    const tokens = await silentRefresh()
    if (!tokens) return false
    const next = sessionFromIdToken(tokens.idToken, {
      tenantId: tokens.tenantId,
      role: tokens.role,
      roles: tokens.roles,
    })
    setActiveTokens({ idToken: tokens.idToken, tokenType: 'cognito' })
    applySession(next)
    scheduleRefresh(next)
    return true
  }

  async function refreshNow(): Promise<void> {
    // Impersonation tokens hard-expire by design and must never be silently
    // refreshed (04_auth_and_session.md) — guard here too, not just in the
    // scheduler, since the Task 05 API client calls this directly on a 401.
    if (getActiveTokenType() === 'impersonation') return
    if (inFlightRefreshRef.current) {
      return inFlightRefreshRef.current
    }
    const pending = (async () => {
      const restored = await restoreFromCookie()
      if (!restored) {
        clearActiveTokens()
        applySession(null)
        setStatus('unauthenticated')
        // Throws (rather than resolving) so the Task 05 API client's 401-recovery
        // path (recoverFrom401) hits its catch block and logs out immediately,
        // instead of retrying the original request with no Authorization header
        // just to get a second, redundant 401.
        throw new Error('Session could not be refreshed')
      }
      setStatus('authenticated')
    })().finally(() => {
      inFlightRefreshRef.current = null
    })
    inFlightRefreshRef.current = pending
    return pending
  }

  // Cross-tab logout sync: signing out in one tab immediately clears sibling tabs.
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const channel = new BroadcastChannel('shipx-auth')
    authChannelRef.current = channel
    channel.onmessage = (event: MessageEvent) => {
      if (event.data === 'logout') {
        clearTimers()
        clearActiveTokens()
        previousRef.current = null
        applySession(null)
        setStatus('unauthenticated')
      }
    }
    return () => {
      channel.close()
      authChannelRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Silent restore on mount — this is what makes a page reload keep the user
  // signed in. The in-memory ID token is gone after any reload (by design,
  // never persisted — see 11_security_and_compliance.md), but the httpOnly
  // refresh-token cookie set by login() below survives it, so the very first
  // thing this provider does is try to trade that cookie for a fresh token
  // before any route ever gets a chance to redirect to /login.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const restored = await restoreFromCookie()
      if (cancelled) return
      setStatus(restored ? 'authenticated' : 'unauthenticated')
    })()
    return () => {
      cancelled = true
    }
    // Mount-only — restoreFromCookie/setStatus are stable within this component instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function login(email: string, password: string, options: { pool?: CognitoPoolKind } = {}): Promise<Session> {
    setStatus('loading')
    try {
      return finishCognitoLogin(await cognitoSignIn(email, password, options))
    } catch (err) {
      setStatus('unauthenticated')
      throw err
    }
  }

  // The second step of a platform admin's sign-in (platform audit Phase 1b): the authenticator code, or the first
  // code from a newly added authenticator app.
  async function completeMfa(step: 'code' | 'setup', code: string): Promise<Session> {
    setStatus('loading')
    try {
      return finishCognitoLogin(await (step === 'code' ? submitMfaCode(code) : verifyMfaSetup(code)))
    } catch (err) {
      setStatus('unauthenticated')
      throw err
    }
  }

  function finishCognitoLogin(tokens: CognitoTokens): Session {
    // A platform-pool token carries no tenant or group claims: the pool itself is the platform-admin grant
    // (shared/platform_identity.py), and the backend directory decides the rest.
    const platform = tokens.pool === 'platform'
    const next = sessionFromIdToken(tokens.idToken, {
      tenantId: platform ? 'PLATFORM' : tokens.tenantId,
      role: platform ? 'platform_admin' : tokens.role,
      roles: platform ? ['platform_admin'] : tokens.roles,
    })
    setActiveTokens({ idToken: tokens.idToken, tokenType: 'cognito' })
    applySession(next)
    setStatus('authenticated')
    scheduleRefresh(next)
    // Persist the refresh token server-side as an httpOnly cookie so a
    // reload can silently restore the session (see restoreFromCookie
    // above). Best-effort: the current tab already has a working session
    // regardless of whether this succeeds — a failure here only means the
    // user won't survive their next reload, not that login itself failed.
    void establishServerSession(tokens.refreshToken, tokens.pool ?? 'tenant').catch((err: unknown) => {
      console.warn('Failed to persist session for reload — will not survive a page refresh', err)
    })
    return next
  }

  // Interactive (Entra) login — a redirect, not an in-app credential exchange.
  // beginLogin navigates away to Entra; completeLogin runs on the /auth/callback
  // route when the browser returns. The httpOnly refresh cookie is set by the
  // backend callback itself, so (unlike Cognito's login) there's no
  // establishServerSession step here — the token already round-tripped the server.
  async function beginLogin(): Promise<void> {
    setStatus('loading')
    try {
      await beginInteractiveLogin()
    } catch (err) {
      setStatus('unauthenticated')
      throw err
    }
  }

  async function completeLogin(code: string, state: string): Promise<Session> {
    setStatus('loading')
    try {
      const tokens = await completeInteractiveLogin(code, state)
      const next = sessionFromIdToken(tokens.idToken, {
        tenantId: tokens.tenantId,
        role: tokens.role,
        roles: tokens.roles,
      })
      setActiveTokens({ idToken: tokens.idToken, tokenType: 'cognito' })
      applySession(next)
      setStatus('authenticated')
      scheduleRefresh(next)
      return next
    } catch (err) {
      setStatus('unauthenticated')
      throw err
    }
  }

  function logout(): void {
    const activeSessionId = session?.readOnly ? session.sessionId : undefined
    const previous = previousRef.current
    const activeIdToken = previous?.idToken ?? getActiveIdToken()
    clearTimers()
    // Best-effort server-side impersonation revocation before clearing tokens so the
    // 30-min HS256 token cannot outlive logout and IMPERSONATION_END is audited.
    if (activeSessionId && previous?.idToken) {
      setActiveTokens({ idToken: previous.idToken, tokenType: 'cognito' })
      void platformApi.endImpersonation(activeSessionId).catch(() => {})
    }
    cognitoSignOut()
    clearActiveTokens()
    previousRef.current = null
    applySession(null)
    setStatus('unauthenticated')
    try {
      authChannelRef.current?.postMessage('logout')
    } catch {
      // BroadcastChannel may be closed during teardown.
    }
    void revokeServerSession(activeIdToken)
  }

  function startImpersonation(idToken: string, tenantName?: string): void {
    if (!session) throw new Error('Cannot start impersonation without an active session')
    // Preserve the original platform admin session even if startImpersonation is called twice.
    if (!previousRef.current) {
      previousRef.current = {
        session,
        idToken: getActiveIdToken() ?? '',
      }
    }
    clearTimers()
    const impSession = sessionFromIdToken(idToken)
    if (tenantName) impSession.tenantName = tenantName
    // Impersonation tokens never refresh — they hard-expire by design. The
    // platform admin's own httpOnly refresh-token cookie is untouched during
    // impersonation, so exitImpersonation needs no token bookkeeping of its
    // own beyond the idToken already saved above.
    setActiveTokens({ idToken, tokenType: 'impersonation' })
    applySession(impSession)

    const delay = impSession.expiresAt - Date.now()
    if (delay > 0) {
      expiryTimer.current = setTimeout(() => {
        exitImpersonation()
        onImpersonationExpire?.()
      }, delay)
    }
  }

  function exitImpersonation(): void {
    const activeSessionId = session?.readOnly ? session.sessionId : undefined
    clearTimers()
    const previous = previousRef.current
    previousRef.current = null
    if (!previous) {
      clearActiveTokens()
      applySession(null)
      setStatus('unauthenticated')
      return
    }
    setActiveTokens({ idToken: previous.idToken, tokenType: 'cognito' })
    applySession(previous.session)
    if (activeSessionId) {
      void platformApi.endImpersonation(activeSessionId).catch(() => {})
    }
    if (previous.session.expiresAt <= Date.now()) {
      void refreshNow().catch(() => {})
    } else {
      scheduleRefresh(previous.session)
    }
  }

  // Client-side-only active-role toggle — never touches the token or fires a
  // request. Authorization stays governed by the full `session.roles` set
  // server-side regardless of which role is "active" here.
  function setActiveRole(role: UserRole): void {
    setSession((prev) => (prev && prev.roles.includes(role) ? { ...prev, role } : prev))
  }

  useRegisterSessionActions({ refreshNow, logout, exitImpersonation })

  // Inactivity timeout. Armed only for a normal authenticated session —
  // impersonation already hard-expires on its own timer (startImpersonation),
  // so it must not also be idle-logged-out mid-task.
  const idleEnabled = status === 'authenticated' && getActiveTokenType() !== 'impersonation'
  const idle = useIdleTimeout({
    idleMs: IDLE_MS,
    warningMs: WARNING_MS,
    enabled: idleEnabled,
    onWarn: (deadline) => setIdleDeadline(deadline),
    onTimeout: () => {
      setIdleDeadline(null)
      logout()
    },
  })

  function staySignedIn(): void {
    setIdleDeadline(null)
    idle.reset()
    // Prove the session is still good and reschedule the proactive refresh.
    void refreshNow().catch(() => undefined)
  }

  function signOutNow(): void {
    setIdleDeadline(null)
    logout()
  }

  return (
    <SessionContext.Provider
      value={{
        session,
        status,
        login,
        completeMfa,
        beginLogin,
        completeLogin,
        logout,
        startImpersonation,
        exitImpersonation,
        refreshNow,
        setActiveRole,
      }}
    >
      {children}
      {idleDeadline !== null && (
        <SessionTimeoutModal deadline={idleDeadline} onContinue={staySignedIn} onSignOut={signOutNow} />
      )}
    </SessionContext.Provider>
  )
}
