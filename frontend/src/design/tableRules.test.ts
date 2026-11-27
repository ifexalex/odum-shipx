/// <reference types="node" />
/**
 * FD-13: one table, one way of reading it. Rows open from their first cell (no "View" button in a column of its own),
 * money columns name their currency, and pages build tables with `Table`, not a hand-made `<table>`.
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
  ([p]) => !p.startsWith('pages/marketing/'),
)

/**
 * Hand-built tables that stay. Print pages lay out paper, not screens. The packing-list item editor is a
 * spreadsheet-style grid with keyboard movement between cells, which `Table` does not do.
 */
const RAW_TABLE_ALLOWED = new Set([
  'pages/china/createPackingList/ItemsTable.tsx',
])

describe('table rules (FD-13)', () => {
  it('no row has a "View" button: the row opens from its first cell', () => {
    const offenders = files.flatMap(([path, text]) =>
      [
        ...text.matchAll(/>\s*View\s*<\/(Button|Link|button|a)>/g),
        ...text.matchAll(/\bViewLink\b/g),
      ].map((m) => `${path}: ${m[0].trim()}`),
    )
    expect(offenders).toEqual([])
  })

  it('every money column names its currency in the title', () => {
    const offenders = files.flatMap(([path, text]) =>
      [...text.matchAll(/title: ['`]([^'`]*)['`], type: 'money'/g)]
        .filter((m) => !/\((₦|\$|¥|\$\{)/.test(m[1]!))
        .map((m) => `${path}: ${m[1]}`),
    )
    expect(offenders).toEqual([])
  })

  it('pages build tables with Table, not a hand-made <table>', () => {
    const offenders = files
      .filter(([path, text]) => /<table\b/.test(text) && !RAW_TABLE_ALLOWED.has(path))
      .map(([p]) => p)
    expect(offenders).toEqual([])
  })

  it('a list states its count once, in the footer', () => {
    // ListFooter carries the count; a second "Showing N" line above the table is the duplicate FD-13 removed.
    const offenders = files
      .filter(([, text]) => /<ListFooter\b/.test(text) && />\s*Showing\s*(\{|<strong)/.test(text))
      .map(([p]) => p)
    expect(offenders).toEqual([])
  })
})
