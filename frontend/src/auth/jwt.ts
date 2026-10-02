import { PLATFORM_TENANT_ID, type Session, type UserRole } from './types'

const VALID_ROLES: ReadonlySet<string> = new Set<UserRole>([
  'platform_admin',
  'tenant_admin',
  'china_office_staff',
  'nigeria_office_staff',
  'warehouse_attendant',
  'customer',
])

export function decodeJwt(token: string): Record<string, unknown> {
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error('Malformed JWT: expected 3 dot-separated segments')

  const base64 = parts[1]!.replace(/-/g, '+').replace(/_/g, '/')
  const json = decodeURIComponent(
    atob(base64)
      .split('')
      .map((char) => '%' + char.charCodeAt(0).toString(16).padStart(2, '0'))
      .join(''),
  )
  return JSON.parse(json) as Record<string, unknown>
}

// Cognito's HTTP API v2 authorizer passes cognito:groups as either a real JSON array,
// an unquoted bracketed string "[group1,group2]" (not valid JSON), or a comma-separated
// string — mirrors shared/auth.py's _parse_role parsing exactly.
function parseGroups(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map(String)
  if (typeof raw !== 'string' || raw.length === 0) return []

  if (raw.startsWith('[')) {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed.map(String)
    } catch {
      // Not valid JSON — fall through to bracket-stripping below.
    }
    return raw
      .slice(1, -1)
      .split(',')
      .map((group) => group.trim())
      .filter(Boolean)
  }

  return raw
    .split(',')
    .map((group) => group.trim())
    .filter(Boolean)
}

// Mirrors shared/auth.py's _parse_roles: the platform_admin group has no tenant
// prefix; tenant users are "{tenant_id}:{role}". Collects every matching group
// (not just the first) so staff can hold more than one role at once. Falls
// back to ['customer'] when nothing matches, matching backend behavior exactly
// rather than introducing a stricter frontend-only rule the backend doesn't enforce.
function parseRoles(groups: string[], tenantId: string): UserRole[] {
  if (groups.includes('platform_admin')) return ['platform_admin']

  const prefix = `${tenantId}:`
  const roles = new Set<UserRole>()
  for (const group of groups) {
    if (group.startsWith(prefix)) {
      const roleStr = group.slice(prefix.length)
      if (VALID_ROLES.has(roleStr)) roles.add(roleStr as UserRole)
    }
  }
  return roles.size > 0 ? Array.from(roles) : ['customer']
}

// Mirrors shared/auth.py's _parse_primary_role: read from the custom:role
// claim (kept in sync by the tenant management service on every role change),
// falling back to a deterministic (alphabetically first) member of `roles`
// when the claim is absent, stale, or names a role the user no longer holds.
function parsePrimaryRole(claims: Record<string, unknown>, roles: UserRole[]): UserRole {
  const claimed = claims['custom:role']
  if (typeof claimed === 'string' && VALID_ROLES.has(claimed) && roles.includes(claimed as UserRole)) {
    return claimed as UserRole
  }
  return [...roles].sort()[0]!
}

export function buildSession(claims: Record<string, unknown>): Session {
  const userId = String(claims.sub ?? '')
  // Cognito ID tokens carry custom:tenant_id; ShipX impersonation tokens
  // (services/tenant_management/impersonation.py) carry a bare tenant_id.
  const tenantId = String(claims['custom:tenant_id'] ?? claims.tenant_id ?? '')
  if (!userId || !tenantId) {
    throw new Error('JWT is missing required claims (sub / custom:tenant_id)')
  }

  // Impersonation tokens have no cognito:groups — they carry the target role
  // directly in a `role` claim instead (single role only). Groups win when present (Cognito path).
  const groups = parseGroups(claims['cognito:groups'])
  const directRole = typeof claims.role === 'string' && VALID_ROLES.has(claims.role) ? (claims.role as UserRole) : null
  const roles: UserRole[] = groups.length > 0 ? parseRoles(groups, tenantId) : [directRole ?? 'customer']
  const role = parsePrimaryRole(claims, roles)

  const impersonatedBy = (claims.impersonated_by as string | undefined) || null
  const sessionId = (claims.session_id as string | undefined) || null
  const readOnlyRaw = String(claims.read_only ?? 'false').toLowerCase()
  const readOnly = readOnlyRaw === 'true' && impersonatedBy != null

  const expSeconds = Number(claims.exp ?? 0)

  const name = typeof claims.name === 'string' && claims.name ? claims.name : null
  const email = typeof claims.email === 'string' && claims.email ? claims.email : null

  return {
    tenantId,
    tenantName: null,
    userId,
    name,
    email,
    role,
    roles,
    isPlatformAdmin: tenantId === PLATFORM_TENANT_ID,
    impersonatedBy,
    sessionId,
    readOnly,
    expiresAt: expSeconds * 1000,
    tokenType: impersonatedBy ? 'impersonation' : 'cognito',
  }
}

export function sessionFromIdToken(idToken: string): Session {
  return buildSession(decodeJwt(idToken))
}
