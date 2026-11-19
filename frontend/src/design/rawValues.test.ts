/// <reference types="node" />
/**
 * Design foundations: visual values come from the tokens in tokens.css, not raw numbers in page styles.
 *
 * - FD-01 type: every font size, line height and letter spacing is a type token; only weights 400-700. A rule that
 *   says `scale-exempt` with a reason (miniature document previews, emoji icons) is skipped. `1` and `0` stay allowed.
 * - FD-02 spacing: every gap, padding and margin is a --space-* token (or 0, auto, a percentage).
 * - FD-03 colour: no raw hex or rgb() colour in a style sheet or an inline style, and no var(--…) that nothing defines
 *   (it renders as nothing: popovers that used the undefined --shadow-lg had no shadow).
 * - FD-04 radius: a --radius-* token, 0, or 50% for a circle.
 * - FD-05 layers, shadows, motion: z-index is a --layer-* token (or -1, 0, 1 inside one component), box-shadow a
 *   --shadow-* token, and transition timing --motion-* with --ease-standard.
 *
 * Exempt everywhere: print pages and the marketing page.
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
/** A px or rem length inside a spacing declaration's value. */
const SPACING = /(?<![-\w])((?:row-|column-)?gap|padding(?:-[a-z-]+)?|margin(?:-[a-z-]+)?):\s*([^;]+);/g
const INLINE_SPACING =
  /\b((?:row|column)?[gG]ap|padding(?:Top|Bottom|Left|Right|Inline|Block)?|margin(?:Top|Bottom|Left|Right|Inline|Block)?):\s*('[^']*'|-?\d+(?:\.\d+)?)(?=\s*[,}\n])/g
const hasLength = (value: string): boolean => /\d(?:px|rem)\b/.test(value) || /^-?[1-9]\d*(?:\.\d+)?$/.test(value)
const ALLOWED_WEIGHTS = new Set(['400', '500', '600', '700', 'inherit', 'normal'])

describe('design foundations: no raw values', () => {
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

  it('no declaration holds a script leftover (None, undefined, NaN), which the browser silently drops', () => {
    // A codemod once wrote Python's None after 1,450 spacing values: the CSS still parsed, every check above passed,
    // and every one of those declarations was dropped. Only the visual baseline showed it.
    const broken: string[] = []
    for (const path of files(SRC, '.css')) {
      for (const [decl] of readFileSync(path, 'utf8').matchAll(/[\w-]+:\s*[^;{}]*\b(?:None|undefined|NaN)\b[^;{}]*;/g)) {
        broken.push(`${relative(SRC, path)}: ${decl.trim()}`)
      }
    }
    expect(broken).toEqual([])
  })

  it('style sheets use colour tokens, never a raw hex or rgb() colour (FD-03)', () => {
    const raw: string[] = []
    for (const path of sheets) {
      for (const [, selector, body] of readFileSync(path, 'utf8').matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
        if (body?.includes('scale-exempt')) continue
        for (const [colour] of (body ?? '').matchAll(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g)) {
          raw.push(`${relative(SRC, path)} ${selector?.trim().split('\n').pop()}: ${colour}`)
        }
      }
    }
    expect(raw, 'use a --color-* token, or color-mix() of one for a tint').toEqual([])
  })

  it('inline styles use colour tokens too (FD-03)', () => {
    const raw: string[] = []
    for (const path of components) {
      for (const [colour] of readFileSync(path, 'utf8').matchAll(/'(?:[\d.]+px \w+ )?(?:#[0-9a-fA-F]{3,8}|rgba?\([^)'\n]*\))'/g)) {
        raw.push(`${relative(SRC, path)}: ${colour}`)
      }
    }
    expect(raw, "use 'var(--color-…)' or a color-mix() of one").toEqual([])
  })

  it('radius, layers, shadows and motion come from their tokens (FD-04, FD-05)', () => {
    const raw: string[] = []
    const keyframeStep = /^(?:[\d.]+%\s*,?\s*)+$|^(?:from|to)$/
    for (const path of sheets) {
      for (const [, selector, body] of readFileSync(path, 'utf8').matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
        const sel = ((selector ?? '').trim().split('\n').pop() ?? '').trim()
        if (!body || body.includes('scale-exempt') || keyframeStep.test(sel)) continue
        const where = `${relative(SRC, path)} ${sel}`
        for (const [, value] of body.matchAll(/(?<![-\w])border(?:-[a-z]+)*-radius:\s*([^;]+);/g)) {
          const parts = (value ?? '').replace('!important', '').trim().split(/\s+/)
          if (!parts.every((v) => /^var\(--radius-(?:sm|md|lg|xl|full)\)$|^0$|^50%$|^inherit$/.test(v))) raw.push(`${where} radius: ${value}`)
        }
        for (const [, value] of body.matchAll(/(?<![-\w])z-index:\s*([^;]+);/g)) {
          const v = (value ?? '').trim()
          if (!/^(?:-1|0|1|auto)$|^var\(--layer-[a-z]+\)$|^calc\(var\(--layer-[a-z]+\) [-+] 1\)$/.test(v)) raw.push(`${where} z-index: ${v}`)
        }
        for (const [, value] of body.matchAll(/(?<![-\w])box-shadow:\s*([^;]+);/g)) {
          const v = (value ?? '').trim()
          if (!/^(?:none|inherit)$|^var\(--shadow-[a-z-]+\)$/.test(v)) raw.push(`${where} box-shadow: ${v}`)
        }
        for (const [, value] of body.matchAll(/(?<![-\w])transition(?:-duration|-timing-function)?:\s*([^;]+);/g)) {
          const v = (value ?? '').trim()
          if (v !== 'none' && (/\d(?:ms|s)\b|ease|linear|cubic-bezier/.test(v.replace(/var\(--(?:motion|ease)-[a-z]+\)/g, '')))) raw.push(`${where} transition: ${v}`)
        }
      }
    }
    expect(raw, 'use --radius-*, --layer-*, --shadow-*, --motion-* and --ease-standard').toEqual([])
  })

  it('every var(--…) names a defined custom property (FD-03)', () => {
    const all = [...files(SRC, '.css'), ...files(SRC, '.tsx'), ...files(SRC, '.ts')].filter((p) => !p.includes('.test.'))
    const defined = new Set<string>()
    const used = new Map<string, string>()
    for (const path of all) {
      const source = readFileSync(path, 'utf8')
      // In a style sheet `--name: value`; set from a component as `'--name': value`.
      for (const [, name] of source.matchAll(/['"]?(--[\w-]+)['"]?\s*:/g)) defined.add(name!)
      // A name built in a template (`var(--radius-${size})`) ends in '-' and is checked where it is used.
      for (const [, name] of source.matchAll(/var\((--[\w-]*\w)\b(?![-$])/g)) if (!used.has(name!)) used.set(name!, relative(SRC, path))
    }
    const undefinedNames = [...used].filter(([name]) => !defined.has(name)).map(([name, where]) => `${name} (${where})`)
    expect(undefinedNames).toEqual([])
  })

  it('style sheets space with --space-* tokens (FD-02)', () => {
    const raw: string[] = []
    for (const path of sheets) {
      for (const [, prop, value] of readFileSync(path, 'utf8').matchAll(SPACING)) {
        if (hasLength((value ?? '').trim())) raw.push(`${relative(SRC, path)} ${prop}: ${value}`)
      }
    }
    expect(raw, 'use var(--space-1) ... var(--space-16)').toEqual([])
  })

  it('inline styles space with --space-* tokens too (FD-02)', () => {
    const raw: string[] = []
    for (const path of components) {
      for (const [match, , value] of readFileSync(path, 'utf8').matchAll(INLINE_SPACING)) {
        if (hasLength((value ?? '').replace(/'/g, '').trim())) raw.push(`${relative(SRC, path)}: ${match}`)
      }
    }
    expect(raw, "use padding: 'var(--space-4)' and the like").toEqual([])
  })
})
