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
    data?: { id_token?: string; tenant_id?: string; role?: string }
    detail?: string
    title?: string
  }
  if (!resp.ok || !body.data?.id_token) {
    throw new Error(body.detail || body.title || 'Sign-in could not be completed. Please try again.')
  }
  // The refresh token stays server-side in the httpOnly cookie the callback set;
  // only the id token comes back, to live in memory. accessToken mirrors it (the
  // app authenticates to its own API with the id token, as on Cognito).
  // tenant_id/role come from the backend: Entra External ID does not emit the
  // claims provider's output into the token, so the SPA cannot read them there.
  return {
    idToken: body.data.id_token,
    accessToken: body.data.id_token,
    refreshToken: '',
    tenantId: body.data.tenant_id ?? null,
    role: body.data.role ?? null,
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
