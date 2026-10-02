// Backend ground truth: shared/tenant_context.py UserRole — string values, exact match required.
export type UserRole =
  | 'platform_admin'
  | 'tenant_admin'
  | 'china_office_staff'
  | 'nigeria_office_staff'
  | 'warehouse_attendant'
  | 'customer'

export const PLATFORM_TENANT_ID = 'PLATFORM'

export type TokenType = 'cognito' | 'impersonation'

// Frontend mirror of the backend's TenantContext (shared/tenant_context.py).
// Parsed once from the decoded JWT on login/refresh — never re-derived from
// the URL, subdomain, or local storage flags (see 04_auth_and_session.md).
export interface Session {
  tenantId: string
  /** Human-readable tenant company name — populated on impersonation start; absent/null for own sessions. */
  tenantName?: string | null
  userId: string
  /** Display name from the Cognito `name` claim. Null when absent (e.g. legacy tokens). */
  name: string | null
  /** Email from the Cognito `email` claim (Username). Absent on impersonation tokens. */
  email?: string | null
  /** Currently active/display role — drives nav/home/breadcrumb. Defaults to the
   *  user's primary role; user-switchable (client-side only) when `roles.length > 1`. */
  role: UserRole
  /** Every role assigned to this user (multi-role staff support). Always includes `role`. */
  roles: UserRole[]
  isPlatformAdmin: boolean
  impersonatedBy: string | null
  sessionId: string | null
  readOnly: boolean
  /** From the JWT `exp` claim, in epoch milliseconds — drives auto-logout / countdown. */
  expiresAt: number
  tokenType: TokenType
}
