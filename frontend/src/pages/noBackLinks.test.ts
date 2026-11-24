/**
 * FD-47: pages carry no hand-written "Back to …" link; the breadcrumb (and its single back link on a phone) is the way
 * back. Allowed: the sign-in flow and print pages (no breadcrumb there), and buttons that are the next action on a
 * result screen rather than navigation chrome (payment received or failed, tenant created).
 */
import { describe, expect, it } from 'vitest'

const SOURCES = import.meta.glob(['./**/*.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

const ALLOWED = new Set([
  './customer/PaymentFailed.tsx',
  './customer/PaymentSuccess.tsx',
  './platform/CreateTenantPage.tsx',
])

describe('no hand-written back links (FD-47)', () => {
  const pages = Object.entries(SOURCES).filter(
    ([path]) => !path.includes('.test.') && !path.startsWith('./auth/') && !ALLOWED.has(path),
  )

  it('finds the pages', () => expect(pages.length).toBeGreaterThan(80))

  it.each(pages)('%s', (_path, source) => {
    expect(source).not.toMatch(/>\s*Back to [A-Za-z]/)
    expect(source).not.toMatch(/navigate\([^)]*\)\}?>\s*Back\s*</)
  })
})
