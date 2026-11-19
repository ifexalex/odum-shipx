import { describe, expect, it } from 'vitest'
import { loginUrlFor, safeNextPath } from './returnPath'

describe('safeNextPath', () => {
  it('accepts an in-app path, keeping its query', () => {
    expect(safeNextPath('/my-billing/abc')).toBe('/my-billing/abc')
    expect(safeNextPath('/containers?status=loading&q=MSCU')).toBe('/containers?status=loading&q=MSCU')
  })

  it.each([
    ['an absolute URL', 'https://example.com'],
    ['a protocol-relative URL', '//example.com'],
    ['a protocol-relative URL with a path', '//example.com/my-billing'],
    ['a backslash variant', '/\\example.com'],
    ['an encoded backslash', '/%5C%5Cexample.com'],
    ['an encoded double slash', '/%2F%2Fexample.com'],
    ['a malformed escape', '/%E0%A4%A'],
    ['an encoded-backslash host trick via backslash', '/\\/example.com'],
    ['a javascript: URL', 'javascript:alert(1)'],
    ['a data: URL', 'data:text/html,<script>'],
    ['a bare host', 'example.com'],
    ['a relative path', 'my-billing/abc'],
    ['a newline smuggled into the path', '/my-billing\n//example.com'],
    ['a tab inside the path', '/my\tbilling'],
    ['an absurdly long value', `/${'a'.repeat(3000)}`],
    ['nothing', ''],
  ])('refuses %s', (_label, value) => {
    expect(safeNextPath(value)).toBeNull()
  })

  it('refuses null and undefined', () => {
    expect(safeNextPath(null)).toBeNull()
    expect(safeNextPath(undefined)).toBeNull()
  })

  it.each(['/', '/login', '/login?next=/x', '/register/acme', '/forgot-password', '/reset-password', '/auth/callback'])(
    'refuses %s: the sign-in screens would loop',
    (value) => {
      expect(safeNextPath(value)).toBeNull()
    },
  )
})

describe('loginUrlFor', () => {
  it('carries the requested page through sign-in', () => {
    expect(loginUrlFor('/my-billing/abc')).toBe('/login?next=%2Fmy-billing%2Fabc')
    expect(loginUrlFor('/containers', '?status=loading')).toBe('/login?next=%2Fcontainers%3Fstatus%3Dloading')
  })

  it('is just /login when there is nowhere worth returning to', () => {
    expect(loginUrlFor('/')).toBe('/login')
    expect(loginUrlFor('/login')).toBe('/login')
  })
})
