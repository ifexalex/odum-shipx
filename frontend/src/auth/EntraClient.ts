// Microsoft Entra (External ID) auth client — the Azure counterpart of
// CognitoClient, exposing the same signIn/refreshSession/signOut surface so the
// app's auth layer is cloud-agnostic (selected in authClient.ts).
//
// Uses the OAuth2 Resource Owner Password Credentials (ROPC) grant so the
// existing email/password LoginScreen works unchanged — no redirect UX. ROPC is
// valid for Entra External ID LOCAL accounts (the ones the Cognito→Entra
// migration provisions); it does not support social/federated logins or MFA. If
// those are needed later, swap this for an MSAL redirect flow behind the same
// authClient seam.
//
// Config (build-time env):
//   VITE_ENTRA_TOKEN_ENDPOINT — full OAuth2 token endpoint, e.g.
//     https://<tenant>.ciamlogin.com/<tenant>.onmicrosoft.com/oauth2/v2.0/token
//   VITE_ENTRA_CLIENT_ID      — the SPA app registration (public) client id
//   VITE_ENTRA_SCOPE          — space-separated scopes (default below)

import type { CognitoTokens } from './CognitoClient'

const DEFAULT_SCOPE = 'openid profile offline_access'

function readEnv(name: string): string {
  const value = import.meta.env[name]
  if (!value) throw new Error(`Missing required env var: ${name}`)
  return value
}

interface EntraTokenResponse {
  id_token?: string
  access_token?: string
  refresh_token?: string
  error?: string
  error_description?: string
}

// Entra returns the current refresh token on ROPC; kept in memory only (never
// persisted), mirroring CognitoClient's posture — see 11_security_and_compliance.md.
let currentRefreshToken: string | null = null

async function requestToken(body: Record<string, string>): Promise<CognitoTokens> {
  const endpoint = readEnv('VITE_ENTRA_TOKEN_ENDPOINT')
  const clientId = readEnv('VITE_ENTRA_CLIENT_ID')
  const scope = import.meta.env.VITE_ENTRA_SCOPE || DEFAULT_SCOPE

  const form = new URLSearchParams({ client_id: clientId, scope, ...body })
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  })
  const data = (await resp.json()) as EntraTokenResponse
  if (!resp.ok || !data.id_token) {
    // Surface Entra's error code as the Error name so LoginScreen can message it.
    const err = new Error(data.error_description || data.error || 'Entra authentication failed')
    err.name = data.error || 'EntraAuthError'
    throw err
  }
  currentRefreshToken = data.refresh_token ?? null
  return {
    idToken: data.id_token,
    accessToken: data.access_token ?? data.id_token,
    refreshToken: data.refresh_token ?? '',
  }
}

// Authenticates directly against Entra — the backend API never sees a password
// (parity with CognitoClient.signIn).
export function signIn(email: string, password: string): Promise<CognitoTokens> {
  return requestToken({ grant_type: 'password', username: email, password })
}

// Silent refresh via the OAuth2 refresh_token grant.
export function refreshSession(refreshToken: string): Promise<CognitoTokens> {
  const token = refreshToken || currentRefreshToken
  if (!token) return Promise.reject(new Error('No Entra refresh token available — sign in first'))
  return requestToken({ grant_type: 'refresh_token', refresh_token: token })
}

export function signOut(): void {
  currentRefreshToken = null
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
