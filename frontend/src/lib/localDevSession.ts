// Deliberately NOT in src/auth/ — frontend-ci.yml's "no localStorage/
// sessionStorage in auth layer" check does a literal grep of src/auth/ and
// fails the build on any match, because that folder must never persist a
// token (11_security_and_compliance.md's in-memory-only rule). This module
// persists no token and no PII: a single boolean marker, read only by
// LocalAuthProvider.tsx (dev-only, gated behind VITE_ENVIRONMENT === 'local',
// never part of the production bundle).
//
// What it's for: LocalAuthProvider always has a fallback "dev identity"
// session (defaults to platform_admin) so engineers land in a working app
// without logging in. That fallback used to unconditionally resurface the
// instant a real Cognito session (logout()) ended — including after a page
// reload, since React state can't survive one — making "log out" of a real
// account appear to silently log the user back in as the dev shim. This flag
// suppresses that fallback until the user explicitly logs in again or picks
// a role from RoleSwitcher, and survives a reload via sessionStorage (cleared
// when the tab closes, same as any other "this session ended" marker).
const KEY = 'shipx_dev_explicit_logout'

export function hasExplicitDevLogout(): boolean {
  try {
    return window.sessionStorage.getItem(KEY) === '1'
  } catch {
    // Privacy mode / storage disabled — falls back to "not logged out",
    // matching this flag's pre-existing absence-is-false behavior.
    return false
  }
}

export function setExplicitDevLogout(): void {
  try {
    window.sessionStorage.setItem(KEY, '1')
  } catch {
    // The synchronous in-memory session clear in logout() still applies for
    // the rest of this page's lifetime; only the "stay logged out across a
    // reload" part of the fix is lost in this environment.
  }
}

export function clearExplicitDevLogout(): void {
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    // See setExplicitDevLogout.
  }
}

// Ground-truth gap found live, reported by the user: "when i am on tab e.g
// customer or any other tab and i refresh, it goes to the dashboard" — on
// *every* page, not just one. Root cause: LocalAuthProvider's dev-shim
// `identity` (which role RoleSwitcher has active) is plain React state with
// nothing persisting it, and App.tsx never passes an `initialRole`, so any
// reload resets it to the 'platform_admin' default. RoleGuard then sees the
// current route's `allow` list no longer includes the (now wrong) role and
// redirects to that role's home page — for platform_admin, a "dashboard"
// page, matching the report exactly. Reproduced directly: switching to
// tenant_admin, opening /admin/customers, and reloading landed on
// /platform/dashboard every time.
//
// This is the same list as auth/LocalRoleContext.ts's DevIdentityKey — not
// importing that type here (only its *values*), since this module is a
// plain data store with no reason to depend on an auth/ type beyond typing
// the string it hands back.
const IDENTITY_KEY = 'shipx_dev_identity'
const VALID_IDENTITIES = [
  'platform_admin',
  'tenant_admin',
  'china_office_staff',
  'nigeria_office_staff',
  'warehouse_attendant',
  'customer',
  'nigeria_warehouse',
] as const

export type PersistedDevIdentity = (typeof VALID_IDENTITIES)[number]

export function getPersistedDevIdentity(): PersistedDevIdentity | null {
  try {
    const stored = window.sessionStorage.getItem(IDENTITY_KEY)
    return (VALID_IDENTITIES as readonly string[]).includes(stored ?? '') ? (stored as PersistedDevIdentity) : null
  } catch {
    return null
  }
}

export function setPersistedDevIdentity(identity: string): void {
  try {
    window.sessionStorage.setItem(IDENTITY_KEY, identity)
  } catch {
    // Best-effort — the switcher still works for the rest of this page's
    // lifetime; only "survives a reload" is lost in this environment.
  }
}

export function clearPersistedDevIdentity(): void {
  try {
    window.sessionStorage.removeItem(IDENTITY_KEY)
  } catch {
    // See setPersistedDevIdentity.
  }
}
