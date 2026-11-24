/// <reference types="node" />
/**
 * FD-10: a stat card holds a number, not a word; text never breaks inside a word or clips; a table inside a card has
 * no frame of its own.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = resolve(process.cwd(), 'src')

function sources(dir: string, ext: string): Array<[string, string]> {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path, ext)
    if (!name.endsWith(ext) || name.includes('.test.')) return []
    return [[relative(SRC, path), readFileSync(path, 'utf8')] as [string, string]]
  })
}

/** CSS that may split inside a word: a gateway's raw response is one long token with no spaces. */
const BREAK_ANYWHERE_ALLOWED = new Set([
  'pages/tenant-admin/NotificationLog.module.css .gatewayResp',
])

describe('card rules (FD-10)', () => {
  it('no stat card shows a word or a status', () => {
    const offenders = sources(join(SRC, 'pages'), '.tsx').flatMap(([path, text]) =>
      [...text.matchAll(/<StatCard\b[^>]*?value=\{\s*(\w*[Ll]abel)\(/gs)].map(
        (m) => `${path}: ${m[1]}(…)`,
      ),
    )
    expect(offenders).toEqual([])
  })

  it('no style breaks inside ordinary words', () => {
    const offenders = sources(SRC, '.css').flatMap(([path, text]) =>
      [
        ...text.matchAll(
          /(\.[\w-]+)\s*\{[^}]*?(overflow-wrap:\s*anywhere|word-break:\s*break-(?:all|word))/g,
        ),
      ]
        .filter((m) => !BREAK_ANYWHERE_ALLOWED.has(`${path} ${m[1]}`))
        .map((m) => `${path} ${m[1]}: ${m[2]}`),
    )
    expect(offenders).toEqual([])
  })

  it('stat cards neither clamp nor cut their text', () => {
    const css = readFileSync(join(SRC, 'design/components/StatCard.module.css'), 'utf8')
    expect(css).not.toMatch(/line-clamp|text-overflow:\s*ellipsis/)
  })

  it('a table inside a card uses the card edge as its frame', () => {
    const css = readFileSync(join(SRC, 'design/components/Table.module.css'), 'utf8')
    expect(css).toMatch(/:global\(\[data-surface='card'\]\) \.wrapper \{\s*border: 0;/)
    expect(readFileSync(join(SRC, 'design/components/Card.tsx'), 'utf8')).toContain(
      'data-surface="card"',
    )
  })
})
