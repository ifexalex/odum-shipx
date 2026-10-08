import type { TokenType, UserRole } from './types'

type ActiveAuth =
  | { kind: 'jwt'; idToken: string; tokenType: TokenType }
  | { kind: 'local'; tenantId: string; role: UserRole; roles: UserRole[]; userId: string }

// Module-level, not React state — see 11_security_and_compliance.md. The API
// client (Task 05) imports getAuthHeaders()/getActiveIdToken() directly; it
// never needs to subscribe to SessionProvider re-renders to read the token.
//
// Deliberately no refresh-token field: the Cognito refresh token never lives
// in JS-reachable memory at all past the single POST /v1/auth/session call
// made right after login (services/auth/handler.py persists it as a Secure,
// HttpOnly cookie instead) — there is structurally nowhere for it to be
// stored here, not just a convention of always passing null.
let active: ActiveAuth | null = null

export function setActiveTokens(auth: { idToken: string; tokenType: TokenType }): void {
  active = { kind: 'jwt', ...auth }
}

// Backend's local dev server (scripts/local_server.py) accepts these headers
// directly in place of a real JWT when VITE_ENVIRONMENT=local — see LocalAuthProvider.
// `role` is always the dev identity's true primary role — deliberately never the
// client-side-only active-role toggle value, so that toggle stays a pure
// display change with zero effect on what the backend sees.
export function setActiveLocalAuth(auth: { tenantId: string; role: UserRole; roles: UserRole[]; userId: string }): void {
  active = { kind: 'local', ...auth }
}

export function clearActiveTokens(): void {
  active = null
}

export function getActiveIdToken(): string | null {
  return active?.kind === 'jwt' ? active.idToken : null
}

export function getActiveTokenType(): TokenType | null {
  return active?.kind === 'jwt' ? active.tokenType : null
}

// For the Task 05 API client: either Authorization + X-Token-Type (JWT mode,
// the latter only while impersonating — the API Gateway authorizer uses it to
// route to HS256 verification instead of Cognito JWKS), or the local dev
// header trio (local mode, see scripts/local_server.py).
export function getAuthHeaders(): Record<string, string> {
  if (!active) return {}
  if (active.kind === 'local') {
    const headers: Record<string, string> = {
      'X-Tenant-ID': active.tenantId,
      'X-Role': active.role,
      'X-User-ID': active.userId,
    }
    if (active.roles.length > 1) headers['X-Roles'] = active.roles.join(',')
    return headers
  }
  const headers: Record<string, string> = { Authorization: `Bearer ${active.idToken}` }
  if (active.tokenType === 'impersonation') headers['X-Token-Type'] = 'impersonation'
  return headers
}
