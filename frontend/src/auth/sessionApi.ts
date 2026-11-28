// Talks to services/auth/handler.py — the httpOnly-cookie session-persistence
// flow. Deliberately not routed through api/client.ts: these calls happen
// before any ID token exists (or while one is expiring), need `credentials:
// 'include'` to carry the auth cookie (api/client.ts's calls never do — the
// cookie is scoped to Path=/v1/auth so it would never be sent to them
// anyway), and must never trigger api/client.ts's own 401-recovery loop
// (which calls back into SessionProvider.refreshNow(), which calls this
// module — a cycle apiRequest() has no business being part of).
//
// The refresh token itself is only ever handled here for the single fetch
// call in establishServerSession() — never assigned to a variable that
// outlives that call, and never returned to any caller.

function apiBaseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (!value) throw new Error('Missing required env var: VITE_API_BASE_URL')
  return value
}

function authUrl(path: string): string {
  return new URL(path, apiBaseUrl()).toString()
}

export interface RefreshedTokens {
  idToken: string
  expiresIn: number
  /** Backend-resolved tenant/role/roles — present when the token itself carries none
   *  (Entra External ID does not emit the claims provider's output). */
  tenantId?: string | null
  role?: string | null
  roles?: string[] | null
}

/**
 * Persists a just-issued Cognito refresh token as a Secure, HttpOnly,
 * SameSite=Strict cookie (services/auth/handler.py) so a later page load can
 * silently restore the session via silentRefresh() below. Call once,
 * immediately after a successful login.
 */
export async function establishServerSession(refreshToken: string, pool: 'tenant' | 'platform' = 'tenant'): Promise<void> {
  // `pool` tells the backend which Cognito app client refreshes this token (platform audit Phase 1b).
  const response = await fetch(authUrl('/v1/auth/session'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken, pool }),
  })
  if (!response.ok) {
    throw new Error(`Failed to establish persistent session (${response.status})`)
  }
}

/**
 * Exchanges the httpOnly cookie (attached automatically by the browser) for a
 * fresh ID token. Returns null on any failure — no cookie, an expired or
 * revoked refresh token, or a network error — which callers treat as "no
 * session to restore," never as an unexpected error to surface.
 */
export async function silentRefresh(): Promise<RefreshedTokens | null> {
  try {
    const response = await fetch(authUrl('/v1/auth/refresh'), {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) return null
    const envelope = (await response.json()) as {
      data: { id_token: string; expires_in: number; tenant_id?: string; role?: string; roles?: string[] }
    }
    return {
      idToken: envelope.data.id_token,
      expiresIn: envelope.data.expires_in,
      tenantId: envelope.data.tenant_id ?? null,
      role: envelope.data.role ?? null,
      roles: Array.isArray(envelope.data.roles) ? envelope.data.roles : null,
    }
  } catch {
    return null
  }
}

/**
 * Revokes the refresh token server-side and clears the cookie. Best-effort —
 * logout must complete client-side (SessionProvider already clears the
 * in-memory session before calling this) even if this request fails.
 */
export async function revokeServerSession(idToken?: string | null): Promise<void> {
  try {
    const headers: Record<string, string> = {}
    if (idToken) headers.Authorization = `Bearer ${idToken}`
    await fetch(authUrl('/v1/auth/logout'), { method: 'POST', credentials: 'include', headers })
  } catch {
    // Network failure on logout is not actionable — the client-side session
    // is already cleared regardless.
  }
}
