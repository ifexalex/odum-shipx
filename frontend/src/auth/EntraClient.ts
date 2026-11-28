// Microsoft Entra (External ID) auth client — interactive auth-code + PKCE via
// a backend-for-frontend (BFF) flow. The Azure counterpart of CognitoClient.
//
// Why BFF and not client-side MSAL: this codebase keeps tokens out of
// JS-reachable storage (httpOnly refresh cookie, in-memory id token — there's a
// CI guard failing the build on localStorage/sessionStorage in src/auth). So the
// backend owns the OAuth secrets: it mints the authorize URL (server-generated
// PKCE challenge + state + nonce in a short-lived httpOnly cookie), and on the
// callback exchanges the code and sets the httpOnly refresh cookie. The SPA only
// redirects and relays the `code`/`state` from the URL — it never holds the
// password, the PKCE verifier, or any token beyond the in-memory id token.
//
// The interactive flow triggers Entra's custom-claims provider (which injects
// tenant_id/role), unlike ROPC — see 04_auth_and_session.md. Config: the SPA
// needs only VITE_API_BASE_URL; the backend holds every ENTRA_* value.

import type { CognitoTokens } from './CognitoClient'

function apiBaseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (!value) throw new Error('Missing required env var: VITE_API_BASE_URL')
  return value
}

function authUrl(path: string): string {
  return new URL(path, apiBaseUrl()).toString()
}

// Begin interactive login: ask the backend for the authorize URL (which also
// sets the httpOnly PKCE/state transaction cookie), then redirect the browser
// to Entra. Never resolves — the page navigates away on success.
export async function beginLogin(): Promise<never> {
  const resp = await fetch(authUrl('/v1/auth/authorize-url'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
  const body = (await resp.json().catch(() => ({}))) as {
    data?: { authorize_url?: string }
    detail?: string
    title?: string
  }
  const url = body.data?.authorize_url
  if (!resp.ok || !url) {
    throw new Error(body.detail || body.title || 'Could not start sign-in. Please try again.')
  }
  window.location.assign(url)
  // Block the caller until the navigation unloads the page.
  return new Promise<never>(() => {})
}

// Complete interactive login: hand the code + state back to the backend, which
// validates state against the transaction cookie, exchanges the code, and sets
// the refresh cookie. Returns the ID token (now carrying tenant_id/role).
export async function completeLogin(code: string, state: string): Promise<CognitoTokens> {
  const resp = await fetch(authUrl('/v1/auth/callback'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, state }),
  })
  const body = (await resp.json().catch(() => ({}))) as {
    data?: { id_token?: string; tenant_id?: string; role?: string; roles?: string[] }
    detail?: string
    title?: string
  }
  if (!resp.ok || !body.data?.id_token) {
    throw new Error(body.detail || body.title || 'Sign-in could not be completed. Please try again.')
  }
  // The refresh token stays server-side in the httpOnly cookie the callback set;
  // only the id token comes back, to live in memory. accessToken mirrors it (the
  // app authenticates to its own API with the id token, as on Cognito).
  // tenant_id/role/roles come from the backend: Entra External ID does not emit
  // the claims provider's output into the token, so the SPA cannot read them there.
  return {
    idToken: body.data.id_token,
    accessToken: body.data.id_token,
    refreshToken: '',
    tenantId: body.data.tenant_id ?? null,
    role: body.data.role ?? null,
    roles: Array.isArray(body.data.roles) ? body.data.roles : null,
  }
}

// Password sign-in is not used on Entra (interactive redirect instead); kept so
// the authClient surface stays uniform. Rejects clearly if ever called.
export function signIn(): Promise<CognitoTokens> {
  return Promise.reject(new Error('Entra uses interactive sign-in — call beginLogin() instead'))
}

// Refresh runs server-side off the httpOnly cookie (sessionApi.silentRefresh →
// POST /v1/auth/refresh); nothing in the app calls this.
export function refreshSession(): Promise<CognitoTokens> {
  return Promise.reject(new Error('Entra refresh is handled server-side via the session cookie'))
}

export function signOut(): void {
  // No client-side Entra state to clear — the httpOnly cookie is cleared by
  // POST /v1/auth/logout (sessionApi.revokeServerSession).
}

// --- Hosted/self-service on Entra; kept for the uniform authClient surface ---

export function hasPendingNewPasswordChallenge(): boolean {
  return false
}

export function completeNewPassword(): Promise<CognitoTokens> {
  return Promise.reject(new Error('New-password challenge is handled by Entra, not in-app'))
}

export function forgotPassword(): Promise<void> {
  return Promise.reject(new Error('Password reset is handled by the Entra hosted flow'))
}

export function confirmForgotPassword(): Promise<void> {
  return Promise.reject(new Error('Password reset is handled by the Entra hosted flow'))
}

// ---------------------------------------------------------------------------
// Step-up re-authentication for platform admins (platform audit Phase 1b)
//
// A dangerous platform action needs a sign-in from the last five minutes. On Entra the console opens a small window
// on the same interactive flow with `purpose: "step_up"`: the backend asks Entra for a fresh sign-in (prompt=login,
// max_age=0) and marks the flow's `state` with `su.`. Like MSAL's pop-up flow, this tab watches the window until it
// is back on our own origin, reads the code and state from its address, closes it, and finishes the exchange itself;
// the backend's callback returns the new ID token without touching the session cookie. The window's own
// /auth/callback page sees the `su.` state and signs nobody in (AuthCallback.tsx).
// ---------------------------------------------------------------------------

const STEP_UP_STATE_PREFIX = 'su.'

/** True for the `state` of a step-up sign-in: the callback page must leave it to the tab that opened the window. */
export function isStepUpState(state: string | null): boolean {
  return Boolean(state?.startsWith(STEP_UP_STATE_PREFIX))
}

/**
 * Open the fresh-sign-in window and resolve with the new ID token. Call from a click handler: the window is opened
 * before any await, so browsers do not block it as a pop-up.
 */
export function beginStepUpSignIn(): Promise<string> {
  const popup = window.open('', 'shipx-step-up', 'popup,width=520,height=680')
  if (!popup) return Promise.reject(new Error('Allow pop-ups for ShipX, then try again.'))
  return new Promise<string>((resolve, reject) => {
    let watch = 0
    const fail = (err: unknown): void => {
      window.clearInterval(watch)
      if (!popup.closed) popup.close()
      reject(err instanceof Error ? err : new Error(String(err)))
    }

    fetch(authUrl('/v1/auth/authorize-url'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ purpose: 'step_up' }),
    })
      .then(async (resp) => {
        const body = (await resp.json().catch(() => ({}))) as { data?: { authorize_url?: string }; detail?: string }
        const url = body.data?.authorize_url
        if (!resp.ok || !url) throw new Error(body.detail || 'Could not start the sign-in.')
        popup.location.href = url
        watch = window.setInterval(() => {
          if (popup.closed) {
            fail(new Error('The sign-in window was closed.'))
            return
          }
          let href: string
          try {
            href = popup.location.href // throws while the window is on Microsoft's pages
          } catch {
            return
          }
          if (!href.startsWith(`${window.location.origin}/auth/callback`)) return
          window.clearInterval(watch)
          const params = new URL(href).searchParams
          popup.close()
          const code = params.get('code')
          const state = params.get('state')
          if (!code || !state) {
            reject(new Error(params.get('error_description') || params.get('error') || 'Sign-in was not completed.'))
            return
          }
          exchangeStepUpCode(code, state).then(resolve, reject)
        }, 200)
      })
      .catch(fail)
  })
}

async function exchangeStepUpCode(code: string, state: string): Promise<string> {
  const resp = await fetch(authUrl('/v1/auth/callback'), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, state }),
  })
  const body = (await resp.json().catch(() => ({}))) as { data?: { id_token?: string; purpose?: string }; detail?: string }
  if (!resp.ok || body.data?.purpose !== 'step_up' || !body.data.id_token) {
    throw new Error(body.detail || 'Sign-in could not be completed.')
  }
  return body.data.id_token
}
