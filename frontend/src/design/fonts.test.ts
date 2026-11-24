/**
 * FD-06: every font the app names is one it ships, served from its own origin, and ₦ is drawn by a face that has it.
 */
/// <reference types="node" />
// Read from disk: Vitest stubs CSS imports, `?raw` included, so they come back empty.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { fonts } from './theme'

/** A file under the frontend root, where Vitest runs. */
const read = (path: string): string => readFileSync(resolve(process.cwd(), path), 'utf8')

const tokens = read('src/design/tokens.css')
const fontsCss = read('src/design/fonts.css')
const indexHtml = read('index.html')

/** The families a CSS font stack names, without quotes or the generic fallback. */
function families(stack: string): string[] {
  return stack
    .split(',')
    .map((name) => name.trim().replace(/^['"]|['"]$/g, ''))
    .filter((name) => !['sans-serif', 'serif', 'monospace'].includes(name))
}

/** Every family fonts.css declares: its own @font-face rules and the @fontsource packages it imports. */
function shippedFamilies(): Set<string> {
  const shipped = new Set<string>()
  const add = (css: string): void => {
    for (const [, name] of css.matchAll(/font-family:\s*'([^']+)'/g)) if (name) shipped.add(name)
  }
  add(fontsCss)
  for (const [, pkg] of fontsCss.matchAll(/@import '(@fontsource-variable\/[^']+)'/g)) {
    if (pkg) add(read(`node_modules/${pkg}/index.css`))
  }
  return shipped
}

describe('fonts (FD-06)', () => {
  const tokenStacks = [...tokens.matchAll(/--font-(display|body|mono):\s*([^;]+);/g)].map(
    ([, , stack]) => stack ?? '',
  )

  it('finds the three font tokens', () => expect(tokenStacks).toHaveLength(3))

  it('names only fonts the app ships, in the CSS tokens and in theme.ts', () => {
    const shipped = shippedFamilies()
    for (const stack of [...tokenStacks, ...Object.values(fonts)]) {
      for (const family of families(stack))
        expect(shipped, `${family} in "${stack}"`).toContain(family)
    }
  })

  it('puts the ₦ face first in every stack, so ₦ never falls back to a system font', () => {
    for (const stack of [...tokenStacks, ...Object.values(fonts)])
      expect(families(stack)[0]).toBe('ShipX Naira')
    expect(fontsCss).toMatch(/unicode-range:\s*U\+20A6;/)
  })

  it('requests no font from another origin', () => {
    expect(indexHtml).not.toMatch(/fonts\.(googleapis|gstatic)\.com/)
    expect(fontsCss).not.toMatch(/url\(['"]?https?:/)
  })
})
