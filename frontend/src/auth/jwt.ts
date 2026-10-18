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

// Frontend port of shared/providers/azure/entra_claims.py (EntraClaimsMapper).
// Entra tokens are not shaped like Cognito's: a cloud-only security group is
// emitted in `groups` as its directory OBJECT ID (a GUID), not the canonical
// "{tenant_id}:{role}"/"platform_admin" name; CIAM also does not reliably emit
// a ShipX tenant_id claim. buildSession applies this ONLY for the Entra provider
// (mirroring get_claims_mapper's provider selection) so Cognito is untouched.
const PLATFORM_ADMIN_GROUP = 'platform_admin'

// Entra group-object-id → ShipX canonical name, built at call time from the
// build-injected env so a token carrying GUIDs resolves without a Graph call.
// Mirrors _load_group_id_map (ENTRA_GROUP_ID_MAP + ENTRA_PLATFORM_ADMIN_GROUP_ID).
function loadEntraGroupIdMap(): Record<string, string> {
  const map: Record<string, string> = {}
  const raw = (import.meta.env.VITE_ENTRA_GROUP_ID_MAP || '').trim()
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
          map[String(k).trim()] = String(v).trim()
        }
      }
    } catch {
      // Malformed config must never silently grant/deny a role — ignore it.
    }
  }
  const platformAdminGid = (import.meta.env.VITE_ENTRA_PLATFORM_ADMIN_GROUP_ID || '').trim()
  if (platformAdminGid) map[platformAdminGid] = PLATFORM_ADMIN_GROUP
  return map
}

// Normalize an Entra token's identity into ShipX's canonical (tenantId, groups)
// shapes — the same output EntraClaimsMapper produces for the backend. Exported
// for direct unit testing. `groups` come back as "{tenant}:{role}"/"platform_admin".
export function normalizeEntraClaims(
  claims: Record<string, unknown>,
  groupIdMap: Record<string, string> = loadEntraGroupIdMap(),
): { tenantId: string; groups: string[] } {
  // Names carried directly or mapped from GUIDs (unmapped GUIDs dropped).
  const mapped: string[] = []
  for (const entry of parseGroups(claims.groups)) {
    if (groupIdMap[entry]) mapped.push(groupIdMap[entry])
    else if (entry.includes(':') || entry === PLATFORM_ADMIN_GROUP) mapped.push(entry)
  }

  const roleClaim = typeof claims.role === 'string' ? claims.role.trim() : ''
  const explicitTenant = String(claims.tenant_id ?? '')
  // A platform admin is tenant-less by definition (tenant_id=PLATFORM); the group
  // that grants the role also fixes the scope. Tenant users need an explicit claim.
  const isPlatformAdmin = mapped.includes(PLATFORM_ADMIN_GROUP) || roleClaim === PLATFORM_ADMIN_GROUP
  const tenantId = explicitTenant || (isPlatformAdmin ? PLATFORM_TENANT_ID : '')

  // Synthesize the canonical group from the role + tenant_id claims (reliable even
  // when `groups` carries only GUIDs) — mirrors _synthesize_groups.
  const synthesized: string[] = []
  if (roleClaim === PLATFORM_ADMIN_GROUP) synthesized.push(PLATFORM_ADMIN_GROUP)
  else if (roleClaim && tenantId) synthesized.push(`${tenantId}:${roleClaim}`)

  const seen = new Set<string>()
  const groups: string[] = []
  for (const name of [...mapped, ...synthesized]) {
    if (!seen.has(name)) {
      seen.add(name)
      groups.push(name)
    }
  }
  return { tenantId, groups }
}

function isEntraProvider(): boolean {
  return (import.meta.env.VITE_AUTH_PROVIDER || 'cognito').toLowerCase() === 'entra'
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
  // Cognito: custom:role; Entra: role (ENTRA_ROLE_CLAIM).
  const claimed = claims['custom:role'] ?? claims.role
  if (typeof claimed === 'string' && VALID_ROLES.has(claimed) && roles.includes(claimed as UserRole)) {
    return claimed as UserRole
  }
  return [...roles].sort()[0]!
}

/**
 * Tenant/role resolved by the BACKEND and returned alongside the token.
 *
 * Entra External ID does not emit the custom-claims provider's `tenant_id`/`role`
 * into the token, so for tenant-scoped users those claims are absent and cannot
 * be read client-side at all. The backend resolves them from the user's
 * `tenant_user` row (keyed by the `oid` that IS in the token) and hands them
 * back; this lets the SPA build a session without depending on Entra emitting
 * custom claims. Values from the token still win when present.
 */
export interface ServerContext {
  tenantId?: string | null
  role?: string | null
}

export function buildSession(claims: Record<string, unknown>, server?: ServerContext): Session {
  // Cognito ID tokens carry `sub`; Entra tokens carry `oid` (object id).
  const userId = String(claims.sub ?? claims.oid ?? '')

  // On Entra, normalize the provider-specific claim shapes (GUID group ids, no
  // tenant_id claim for platform admins) into ShipX's canonical tenant_id +
  // groups first — mirroring EntraClaimsMapper. On Cognito these are carried
  // verbatim. Impersonation tokens carry a bare `tenant_id` + `role` on either.
  const entra = isEntraProvider() ? normalizeEntraClaims(claims) : null
  // Cognito: custom:tenant_id; Entra: derived above; impersonation: bare tenant_id.
  // Falls back to the backend-resolved context when the token carries no tenant
  // claim at all (see ServerContext).
  const tenantId =
    (entra ? entra.tenantId : String(claims['custom:tenant_id'] ?? claims.tenant_id ?? '')) ||
    String(server?.tenantId ?? '')
  if (!userId || !tenantId) {
    throw new Error('JWT is missing required claims (sub|oid / tenant id)')
  }

  // Role groups in canonical `{tenant_id}:{role}` / `platform_admin` form:
  // Cognito `cognito:groups`; Entra normalized above. Impersonation tokens have
  // neither — they carry the target role directly in a `role` claim (single role).
  let groups = entra ? entra.groups : parseGroups(claims['cognito:groups'] ?? claims.groups)
  // Same for the role: with no role claim, the group-derived default ('customer')
  // would be wrong, so synthesize the canonical group from the server's answer.
  if (groups.length === 0 && server?.role && tenantId) {
    groups = [server.role === 'platform_admin' ? 'platform_admin' : `${tenantId}:${server.role}`]
  }
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

export function sessionFromIdToken(idToken: string, server?: ServerContext): Session {
  return buildSession(decodeJwt(idToken), server)
}
