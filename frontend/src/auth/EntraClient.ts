// Microsoft Entra (External ID) auth client — the Azure counterpart of
// CognitoClient, exposing the same signIn/refreshSession/signOut surface so the
// app's auth layer is cloud-agnostic (selected in authClient.ts).
//
// Login goes through the BACKEND, not Entra directly. Entra's token endpoint
// sends no Access-Control-Allow-Origin header for the ROPC password grant, so a
// browser fetch to it is CORS-blocked. `services/auth/handler.py` (POST
// /v1/auth/login) runs that exchange server-side and returns the tokens, so the
// existing email/password LoginScreen works unchanged — no redirect UX, no CORS.
// (Token refresh is likewise server-side via the httpOnly-cookie flow in
// sessionApi.ts → POST /v1/auth/refresh, so this module's refreshSession is not
// part of the live path.) ROPC is valid only for Entra local accounts without
// MFA; for social/federated/MFA, swap in an MSAL redirect flow behind this seam.

import type { CognitoTokens } from './CognitoClient'

function apiBaseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (!value) throw new Error('Missing required env var: VITE_API_BASE_URL')
  return value
}

interface LoginEnvelope {
  data?: { id_token?: string; access_token?: string; refresh_token?: string }
  detail?: string
  title?: string
  error_code?: string
}

// Authenticates via the backend ROPC proxy — the browser never calls Entra and
// the API never persists the password (parity with CognitoClient.signIn, which
// talks to Cognito's own CORS-enabled endpoint client-side).
export async function signIn(email: string, password: string): Promise<CognitoTokens> {
  let resp: Response
  try {
    resp = await fetch(new URL('/v1/auth/login', apiBaseUrl()).toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: email, password }),
    })
  } catch {
    const err = new Error('Could not reach the server. Check your connection and try again.')
    err.name = 'NetworkError'
    throw err
  }

  const body = (await resp.json().catch(() => ({}))) as LoginEnvelope
  if (!resp.ok || !body.data?.id_token) {
    // 400/401 from the proxy means Entra rejected the credentials (invalid_grant)
    // — surface a credentials message; anything else is a server/config fault.
    const credsProblem = resp.status === 400 || resp.status === 401
    const err = new Error(
      credsProblem
        ? 'Check your email and password and try again.'
        : body.detail || body.title || 'Sign-in failed. Please try again.',
    )
    err.name = body.error_code || 'EntraAuthError'
    throw err
  }

  return {
    idToken: body.data.id_token,
    accessToken: body.data.access_token ?? body.data.id_token,
    refreshToken: body.data.refresh_token ?? '',
  }
}

// Refresh runs server-side off the httpOnly cookie (sessionApi.silentRefresh →
// POST /v1/auth/refresh); nothing in the app calls this. Kept only to satisfy
// the shared authClient surface, and rejects clearly if ever invoked.
export function refreshSession(): Promise<CognitoTokens> {
  return Promise.reject(new Error('Entra refresh is handled server-side via the session cookie'))
}

export function signOut(): void {
  // No client-side Entra state to clear — the httpOnly cookie is revoked/cleared
  // by POST /v1/auth/logout (sessionApi.revokeServerSession).
}

// --- Flows Entra services through its own hosted experience, not in-app ---
// These keep the CognitoClient surface so authClient can re-export uniformly,
// but on Entra password management is a hosted/self-service flow.

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
