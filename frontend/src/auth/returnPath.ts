// Where a signed-out visitor was heading, so login can take them there afterwards. Links in emails, SMS and
// WhatsApp point at an invoice or a shipment; without this, login always landed on the role's home page.
//
// `next` arrives in a URL, so it is untrusted input and is only ever used as a same-app path. An absolute URL,
// a protocol-relative one (//host) and the backslash variants browsers normalise into them are all refused;
// otherwise a login link could be turned into an open redirect to a phishing page.

const MAX_LENGTH = 2000

// Screens that are themselves part of signing in: returning to one would loop.
const AUTH_SCREENS = ['/login', '/register', '/get-started', '/forgot-password', '/reset-password', '/auth/callback', '/payment-failed']

/** The path to return to, or null if it is missing, not a plain in-app path, or is a sign-in screen. */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw || raw.length > MAX_LENGTH) return null
  // eslint-disable-next-line no-control-regex
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\') || /[\u0000-\u001f\u007f]/.test(raw)) return null
  let parsed: URL
  try {
    parsed = new URL(raw, 'http://app.invalid')
  } catch {
    return null
  }
  if (parsed.origin !== 'http://app.invalid') return null
  // Encoded forms of the same tricks (%5C for a backslash, %2F%2F for //) are refused too.
  let decoded: string
  try {
    decoded = decodeURIComponent(parsed.pathname)
  } catch {
    return null
  }
  if (decoded.includes('\\') || decoded.startsWith('//')) return null
  if (parsed.pathname === '/' || AUTH_SCREENS.some((s) => parsed.pathname === s || parsed.pathname.startsWith(`${s}/`))) return null
  return `${parsed.pathname}${parsed.search}`
}

/** `/login`, carrying the page the visitor asked for when it is worth returning to. */
export function loginUrlFor(pathname: string, search = ''): string {
  const next = safeNextPath(`${pathname}${search}`)
  return next ? `/login?next=${encodeURIComponent(next)}` : '/login'
}
