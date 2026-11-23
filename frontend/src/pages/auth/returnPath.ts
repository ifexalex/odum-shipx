import { safeNextPath } from '../../auth/returnPath'

// The interactive (Entra) sign-in leaves the app and comes back to /auth/callback, so the page the visitor
// wanted has to survive the round trip somewhere. It is a path, not a credential, and it is only ever read back
// through safeNextPath. Kept here, not in src/auth/: that folder must never touch web storage
// (11_security_and_compliance.md; enforced in CI).
const KEY = 'shipx_login_next'

export function rememberNext(next: string | null): void {
  try {
    if (next) window.sessionStorage.setItem(KEY, next)
    else window.sessionStorage.removeItem(KEY)
  } catch {
    // Storage can be blocked; the visitor then lands on their home page, as before.
  }
}

/** The remembered path if it is still safe, and forget it either way: it is good for one sign-in. */
export function takeNext(): string | null {
  try {
    const value = window.sessionStorage.getItem(KEY)
    window.sessionStorage.removeItem(KEY)
    return safeNextPath(value)
  } catch {
    return null
  }
}
