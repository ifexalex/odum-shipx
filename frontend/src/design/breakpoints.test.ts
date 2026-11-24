/// <reference types="node" />
/**
 * FD-35: the app changes layout at three widths only, 600, 860 and 1200 px (phone, tablet, desktop), so neighbouring
 * parts of a page never switch at different widths. Every `@media` and every `@container sxapp` rule (the app's width)
 * must use one of them; `min-width` takes the next pixel (601, 861, 1201) or the width itself.
 *
 * Container queries on a component's own width (a table turning into cards, a stat card too narrow for its icon) are
 * that component's behaviour and are not counted.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = resolve(process.cwd(), 'src')
const BREAKPOINTS = new Set([600, 860, 1200])

function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? cssFiles(path) : path.endsWith('.css') ? [path] : []
  })
}

describe('three breakpoints (FD-35)', () => {
  const files = cssFiles(SRC)

  it('finds the styles', () => expect(files.length).toBeGreaterThan(80))

  it('uses only 600, 860 and 1200 px for the app and the viewport', () => {
    const off: string[] = []
    for (const file of files) {
      const css = readFileSync(file, 'utf8')
      for (const m of css.matchAll(/@(?:media|container sxapp)\s*\(\s*(max|min)-width:\s*(\d+)px/g)) {
        const width = Number(m[2]) - (m[1] === 'min' && BREAKPOINTS.has(Number(m[2]) - 1) ? 1 : 0)
        if (!BREAKPOINTS.has(width)) off.push(`${relative(SRC, file)}: ${m[0]}`)
      }
    }
    expect(off).toEqual([])
  })
})
