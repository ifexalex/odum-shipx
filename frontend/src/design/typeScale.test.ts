/// <reference types="node" />
/**
 * FD-01: every font size, line height and letter spacing on screen comes from the type scale in tokens.css, and only
 * weights 400-700 are used. Exempt: print pages, the marketing page, and a rule that says `scale-exempt` with a reason
 * (miniature document previews, emoji icons). `1` and `0` stay allowed (a single-line box, no spacing).
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

// Read from disk: Vitest stubs CSS imports, `?raw` included.
const SRC = join(process.cwd(), 'src')
const EXEMPT_DIRS = ['pages/print/', 'pages/marketing/']
const EXEMPT_FILES = new Set(['design/tokens.css', 'design/fonts.css'])

function files(dir: string, ext: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return files(path, ext)
    return entry.name.endsWith(ext) ? [path] : []
  })
}

const inScope = (path: string): boolean => {
  const rel = relative(SRC, path)
  return !EXEMPT_DIRS.some((dir) => rel.startsWith(dir)) && !EXEMPT_FILES.has(rel) && !rel.includes('.test.')
}

const RAW = /(?<![-\w])(font-size|line-height|letter-spacing):\s*(-?[\d.]+[a-z%]*)\s*;/g
const WEIGHT = /(?<![-\w])font-weight:\s*([^;]+);/g
const ALLOWED_RAW = new Set(['0', '1'])
const ALLOWED_WEIGHTS = new Set(['400', '500', '600', '700', 'inherit', 'normal'])

describe('type scale (FD-01)', () => {
  const sheets = files(SRC, '.css').filter(inScope)
  const components = files(SRC, '.tsx').filter(inScope)

  it('finds the style sheets and components', () => {
    expect(sheets.length).toBeGreaterThan(60)
    expect(components.length).toBeGreaterThan(150)
  })

  it('style sheets use type tokens, not raw sizes, line heights or letter spacing', () => {
    const raw: string[] = []
    for (const path of sheets) {
      const css = readFileSync(path, 'utf8')
      for (const [, selector, body] of css.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
        if (!body || body.includes('scale-exempt')) continue
        for (const [, prop, value] of body.matchAll(RAW)) {
          if (!ALLOWED_RAW.has(value ?? '')) raw.push(`${relative(SRC, path)} ${selector?.trim().split('\n').pop()} ${prop}: ${value}`)
        }
        for (const [, value] of body.matchAll(WEIGHT)) {
          if (!ALLOWED_WEIGHTS.has((value ?? '').trim())) raw.push(`${relative(SRC, path)} font-weight: ${value}`)
        }
      }
    }
    expect(raw, 'use var(--text-*), var(--text-*-line), var(--leading-*) or var(--tracking-*)').toEqual([])
  })

  it('inline styles use type tokens too', () => {
    const raw: string[] = []
    for (const path of components) {
      const source = readFileSync(path, 'utf8')
      for (const [match, value] of source.matchAll(/\b(?:fontSize|letterSpacing|lineHeight):\s*('?-?[\d.]+[a-z]*'?)/g)) {
        if (!ALLOWED_RAW.has((value ?? '').replace(/'/g, ''))) raw.push(`${relative(SRC, path)}: ${match}`)
      }
      for (const [match, value] of source.matchAll(/\bfontWeight:\s*'?(\d+)'?/g)) {
        if (!ALLOWED_WEIGHTS.has(value ?? '')) raw.push(`${relative(SRC, path)}: ${match}`)
      }
    }
    expect(raw, "use fontSize: 'var(--text-sm)' and the like").toEqual([])
  })
})
