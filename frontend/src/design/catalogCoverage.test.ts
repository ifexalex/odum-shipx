/// <reference types="node" />
/**
 * Step 2 gate: the component catalog renders every component the design system exports, so each variant and state
 * can be checked in light and dark (the catalog has a theme switch).
 */
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const DESIGN = resolve(process.cwd(), 'src/design')

describe('component catalog coverage', () => {
  it('renders every exported component', () => {
    const index = readFileSync(join(DESIGN, 'components/index.ts'), 'utf8')
    const catalog = readFileSync(join(DESIGN, 'ComponentCatalog.tsx'), 'utf8')
    const components = [...index.matchAll(/^export \{ ([^}]+) \}/gm)]
      .flatMap((m) => m[1]!.split(','))
      .map((name) => name.trim())
      .filter((name) => /^[A-Z][a-z]/.test(name))
    expect(components.length).toBeGreaterThan(40)
    const missing = components.filter((name) => !new RegExp(`<${name}\\b`).test(catalog))
    expect(missing).toEqual([])
  })

  it('offers the theme switch', () => {
    expect(readFileSync(join(DESIGN, 'ComponentCatalog.tsx'), 'utf8')).toMatch(/<ThemeToggle\b/)
  })
})
