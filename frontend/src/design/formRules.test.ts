/// <reference types="node" />
/**
 * FD-11 / FD-50: every form control in pages goes through the Field family (Field, Select, DateField, ColorField,
 * SearchField, CellInput/CellSelect/CellCheckbox/CellRadio, RadioGroup, CheckboxField, FileInput), each of which
 * requires a label; filter bars have one date control; required fields carry no asterisk.
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

const pages = sources(join(SRC, 'pages')).filter(
  ([p]) => !p.startsWith('pages/marketing/'),
)

describe('form rules (FD-11, FD-50)', () => {
  it('finds the pages it is meant to police', () => {
    expect(pages.length).toBeGreaterThan(80)
  })

  it('pages write no raw <input>, <select> or <textarea>', () => {
    const offenders = pages.flatMap(([path, text]) =>
      [...text.matchAll(/<(input|select|textarea)\b/g)].map((m) => `${path}: <${m[1]}>`),
    )
    expect(offenders).toEqual([])
  })

  it('filter bars use the one date control, not separate From/To date inputs', () => {
    const offenders = pages
      .filter(([, text]) => /customDateInput|type="date"/.test(text))
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })

  it('marks no required field with an asterisk (forms mark the optional ones)', () => {
    const offenders = pages
      .filter(([, text]) => />\s*\*\s*<\/span>/.test(text))
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })
})
