/**
 * Drift guard for FE-04. Every modal dialog in the app has to get focus handling: either it is a `Modal`, or its
 * overlay contains a `<DialogGuard>`. A hand-rolled dialog that does neither lets Tab walk into the page behind it,
 * has no Escape, and is announced without a name. (Most dialogs here were hand-rolled, which is why the guard exists.)
 */
import { describe, expect, it } from 'vitest'

const SOURCES = import.meta.glob(['../pages/**/*.tsx', '../shell/**/*.tsx', '../design/components/*.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const count = (text: string, needle: RegExp): number => (text.match(needle) ?? []).length

describe('modal dialogs have focus management', () => {
  const files = Object.entries(SOURCES).filter(([path]) => !path.includes('.test.') && !path.endsWith('/Modal.tsx'))

  it('finds the dialogs it is meant to check', () => {
    const modalDialogs = files.reduce((n, [, text]) => n + count(text, /aria-modal="true"/g), 0)
    expect(modalDialogs).toBeGreaterThan(25)
  })

  it.each(files.filter(([, text]) => text.includes('aria-modal="true"')))(
    '%s guards every hand-rolled modal it declares',
    (_path, text) => {
      const dialogs = count(text, /aria-modal="true"/g)
      const guards = count(text, /<DialogGuard\b/g)
      expect(guards, `${dialogs} aria-modal dialog(s) but ${guards} <DialogGuard>`).toBeGreaterThanOrEqual(dialogs)
    },
  )
})

describe('no native browser dialogs (UX-11)', () => {
  // `window.confirm`/`alert`/`prompt` block the page, cannot be styled or translated, and look like a browser
  // warning rather than part of the app. Use `Modal` with a `danger` button for a destructive confirmation.
  const ALL_SOURCES = import.meta.glob(['../**/*.ts', '../**/*.tsx'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>
  // `window.confirm(` or a bare `confirm(`; not a method that happens to share the name (`paymentClaimApi.confirm(`).
  const NATIVE = /(?:\bwindow\.|(?<![.\w]))(?:confirm|alert|prompt)\s*\(/

  it.each(Object.entries(ALL_SOURCES).filter(([path]) => !path.includes('.test.')))('%s', (_path, text) => {
    const code = text.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '')
    expect(code).not.toMatch(NATIVE)
  })
})
