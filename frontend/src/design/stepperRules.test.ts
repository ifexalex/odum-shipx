/// <reference types="node" />
/**
 * FD-09: every progress row is the shared Stepper. Pages do not style their own step dots and lines.
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

describe('stepper rules (FD-09)', () => {
  it('no page stylesheet draws its own step dots or lines', () => {
    const offenders = sources(join(SRC, 'pages'), '.css').flatMap(([path, text]) =>
      [...text.matchAll(/\.(step(?:Dot|Line|Circle)\w*|stepper)\b/g)].map((m) => `${path}: .${m[1]}`),
    )
    expect(offenders).toEqual([])
  })

  it('every page that shows progress steps uses Stepper', () => {
    const users = [
      'pages/china/containerDetail/Timeline.tsx',
      'pages/customer/CustomerStepper.tsx',
      'pages/nigeria/ClaimDetail.tsx',
      'pages/customer/MyClaimDetail.tsx',
      'pages/nigeria/RefundDetail.tsx',
      'pages/china/createPackingList/WizardSteps.tsx',
      'pages/china/ImportPackingLists.tsx',
    ]
    const missing = users.filter((p) => !/<Stepper\b/.test(readFileSync(join(SRC, p), 'utf8')))
    expect(missing).toEqual([])
  })
})
