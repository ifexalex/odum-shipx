/**
 * FD-24: a destructive action never looks like a safe one. Every button whose words cancel, reject, deactivate,
 * suspend, offboard, delete, revoke, withdraw or erase a record is styled `danger` or `danger-ghost` (red), never
 * brand green, neutral secondary or a plain ghost; and each is confirmed (`ConfirmDialog`, or the page's own dialog
 * that asks for a reason). Menu items carry `tone: 'danger'` instead and are not buttons here.
 */
import { describe, expect, it } from 'vitest'

const PAGES = import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

const DESTRUCTIVE = /\b(Cancel (container|billing|invoice|tenant)|Reject\b|Deactivate|Suspend|Offboard|Delete|Revoke|Withdraw|Erase)/

function destructiveButtons(source: string): Array<{ label: string; variant: string }> {
  const found: Array<{ label: string; variant: string }> = []
  // The opening tag may hold arrow functions (`=>`), so its end is a `>` not preceded by `=`.
  for (const match of source.matchAll(/<(Button|Action)\b((?:=>|[^>])*)>\s*([^<{]{2,80}?)\s*<\/\1>/g)) {
    const label = match[3]!.replace(/\s+/g, ' ').trim()
    if (!DESTRUCTIVE.test(label)) continue
    const variant = /variant="([\w-]+)"/.exec(match[2]!)?.[1] ?? 'primary'
    found.push({ label, variant })
  }
  return found
}

describe('destructive actions look destructive (FD-24)', () => {
  const pages = Object.entries(PAGES)

  it('finds them', () => {
    expect(pages.flatMap(([, s]) => destructiveButtons(s)).length).toBeGreaterThan(10)
  })

  it.each(pages.map(([path]) => path))('%s styles every destructive button as danger', (path) => {
    const wrong = destructiveButtons(PAGES[path]!).filter((b) => b.variant !== 'danger' && b.variant !== 'danger-ghost')
    expect(wrong).toEqual([])
  })
})
