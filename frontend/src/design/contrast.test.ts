/// <reference types="node" />
/**
 * FD-03: every text and control colour pair in tokens.css meets WCAG AA, in the light and the dark theme.
 *
 * Text needs 4.5:1 against every surface it sits on; a control's border needs 3:1 (WCAG 1.4.11). The pairs are the
 * ones the design uses: body and muted text on the three surfaces, status and role colours as text, badge text on its
 * soft fill, white on the filled buttons and the dark brand surfaces, and the translucent on-dark text tokens on the
 * forest-green surfaces. A token that changes so a pair fails, fails here with the measured ratio.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// Read from disk: Vitest stubs CSS imports, `?raw` included.
const css = readFileSync(resolve(process.cwd(), 'src/design/tokens.css'), 'utf8')

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`)
  if (start < 0) throw new Error(`no ${selector} block in tokens.css`)
  const body = css.slice(start, css.indexOf('\n}', start))
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(([, name, value]) => [name, value!.trim()]))
}

const light = block(':root')
const themes = { light, dark: { ...light, ...block(":root[data-theme='dark']") } }

type Rgba = [number, number, number, number]

function parse(value: string, tokens: Record<string, string>): Rgba {
  const ref = value.match(/^var\((--[\w-]+)\)$/)
  if (ref) return parse(tokens[ref[1]!] ?? '', tokens)
  const hex = value.match(/^#([0-9a-f]{6}|[0-9a-f]{3})$/i)
  if (hex) {
    const h = hex[1]!.length === 3 ? [...hex[1]!].map((c) => c + c).join('') : hex[1]!
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).concat(1) as Rgba
  }
  const rgba = value.match(/^rgba?\(([\d.\s,]+)\)$/)
  if (rgba) {
    const [r, g, b, a = 1] = rgba[1]!.split(',').map(Number)
    return [r!, g!, b!, a]
  }
  throw new Error(`cannot read colour "${value}"`)
}

/** A translucent colour composited over an opaque background. */
function over([r, g, b, a]: Rgba, [br, bg, bb]: Rgba): Rgba {
  return [r * a + br * (1 - a), g * a + bg * (1 - a), b * a + bb * (1 - a), 1]
}

function luminance([r, g, b]: Rgba): number {
  const channel = (c: number): number => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

function ratio(fg: string, bg: string, tokens: Record<string, string>): number {
  const back = parse(`var(${bg})`, tokens)
  const [l1, l2] = [luminance(over(parse(`var(${fg})`, tokens), back)), luminance(back)].sort((a, b) => b - a)
  return (l1! + 0.05) / (l2! + 0.05)
}

const SURFACES = ['--color-surface', '--color-surface-muted', '--color-page']
const TEXT = [
  '--color-ink',
  '--color-ink-2',
  '--color-ink-3',
  '--color-ink-4',
  '--color-primary-text',
  '--color-accent-text',
  '--color-success',
  '--color-warning',
  '--color-error',
  '--color-info',
]
const ROLE_TEXT = ['platform', 'admin', 'china', 'nigeria', 'warehouse', 'customer'].map((r) => `--color-role-${r}`)
const ON_SOFT: Array<[string, string]> = [
  ['--color-primary-on-soft', '--color-primary-soft'],
  ['--color-accent-on-soft', '--color-accent-soft'],
  ['--color-success-strong', '--color-success-soft'],
  ['--color-warning-strong', '--color-warning-soft'],
  ['--color-error-strong', '--color-error-soft'],
  ['--color-info-strong', '--color-info-soft'],
  ['--color-role-platform-text', '--color-role-platform-soft'],
]
const FILLED = [
  '--color-primary',
  '--color-primary-strong',
  '--color-primary-deep',
  '--color-accent',
  '--color-success-fill',
  '--color-error-fill',
  '--color-forest-dark',
]
/** On-dark text and the dark surfaces it is used on: subtle only on the darkest. */
const ON_DARK: Array<[string, string]> = [
  ['--color-on-dark', '--color-forest-dark'],
  ['--color-on-dark', '--color-primary-deep'],
  ['--color-on-dark-muted', '--color-forest-dark'],
  ['--color-on-dark-muted', '--color-primary-deep'],
  ['--color-on-dark-subtle', '--color-forest-dark'],
]

describe.each(Object.entries(themes))('colour contrast, %s theme (FD-03)', (_name, tokens) => {
  const fails = (pairs: Array<[string, string]>, min: number): string[] =>
    pairs.map(([fg, bg]) => [fg, bg, ratio(fg, bg, tokens)] as const).filter(([, , r]) => r < min).map(([fg, bg, r]) => `${fg} on ${bg}: ${r.toFixed(2)}`)

  it('text and status colours read at 4.5:1 on every surface', () => {
    expect(fails(TEXT.flatMap((t) => SURFACES.map((s) => [t, s] as [string, string])), 4.5)).toEqual([])
  })

  it('role colours read at 4.5:1 on the card surface', () => {
    expect(fails(ROLE_TEXT.map((r) => [r, '--color-surface']), 4.5)).toEqual([])
  })

  it('badge text reads at 4.5:1 on its soft fill', () => {
    expect(fails(ON_SOFT, 4.5)).toEqual([])
  })

  it('white reads at 4.5:1 on every filled button and dark brand surface', () => {
    expect(fails(FILLED.map((f) => ['--color-on-brand', f]), 4.5)).toEqual([])
  })

  it('on-dark text reads at 4.5:1 on the forest-green surfaces', () => {
    expect(fails(ON_DARK, 4.5)).toEqual([])
  })

  it('control borders stand out at 3:1 from every surface', () => {
    expect(fails(SURFACES.map((s) => ['--color-control-border', s]), 3)).toEqual([])
  })
})
