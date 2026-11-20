/// <reference types="node" />
/**
 * FD-20: no page shows a bare "Loading…" or a plain-text empty table; they use the skeletons and EmptyState.
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

const files = [...sources(join(SRC, 'pages')), ...sources(join(SRC, 'shell'))].filter(
  ([p]) => !p.startsWith('pages/marketing/') && !p.startsWith('pages/print/'),
)

describe('state rules (FD-20)', () => {
  it('no page writes a bare "Loading…"', () => {
    const offenders = files.flatMap(([path, text]) =>
      [...text.matchAll(/>\s*Loading[^<{]*…\s*</g), ...text.matchAll(/'Loading[^']*…'/g)].map(
        (m) => `${path}: ${m[0].trim()}`,
      ),
    )
    expect(offenders).toEqual([])
  })

  it('no table shows a plain-text empty state', () => {
    const offenders = files.flatMap(([path, text]) =>
      [...text.matchAll(/emptyState=\{[^}]*?<span\b/g)].map(() => path),
    )
    expect(offenders).toEqual([])
  })
})
