/// <reference types="node" />
/**
 * FD-07: button usage rules, checked across the source.
 *
 * - Pages write no raw <button>: Button, IconButton, a router Link (navigation) or Pressable (a clickable tile/row).
 * - Accent (Kola copper) is for paying and signing in only.
 * - Direction is a trailing icon, never an arrow typed at the end of a label.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = resolve(process.cwd(), 'src')

function sources(dir: string): Array<[string, string]> {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    if (!name.endsWith('.tsx') || name.includes('.test.')) return []
    return [[relative(SRC, path), readFileSync(path, 'utf8')] as [string, string]]
  })
}

// Marketing and print pages are standalone documents with their own styling (as for the design-token guards).
const pages = sources(join(SRC, 'pages')).filter(
  ([p]) => !p.startsWith('pages/marketing/'),
)
const app = [...pages, ...sources(join(SRC, 'shell')), ...sources(join(SRC, 'auth'))]

/** Where accent is allowed: signing in (auth screens, the session-timeout prompt) and paying (the customer invoice). */
const ACCENT_ALLOWED = [
  /^pages\/auth\//,
  /^auth\/SessionTimeoutModal\.tsx$/,
  /^pages\/customer\/MyBillingDetail\.tsx$/,
  /^pages\/customer\/MyShipmentDetail\.tsx$/, // "Pay outstanding"
]

describe('button rules (FD-07)', () => {
  it('finds the pages it is meant to police', () => {
    expect(pages.length).toBeGreaterThan(80)
  })

  it('pages write no raw <button>', () => {
    const offenders = pages.filter(([, text]) => /<button\b/.test(text)).map(([path]) => path)
    expect(offenders).toEqual([])
  })

  it('keeps accent to paying and signing in', () => {
    const offenders = app
      .filter(
        ([path, text]) =>
          /variant="accent"|variant=\{[^}]*'accent'/.test(text) &&
          !ACCENT_ALLOWED.some((rx) => rx.test(path)),
      )
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })

  it('puts direction in an icon, not a typed arrow at the end of a label', () => {
    const offenders = app.flatMap(([path, text]) =>
      [...text.matchAll(/[→←]\s*<\/(?:Button|Link|Pressable|a)>/g)].map(() => path),
    )
    expect(offenders).toEqual([])
  })
})
