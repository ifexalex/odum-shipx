/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest'
import { INVALIDATION_RULES, ruleForPath } from './cacheInvalidation'

// Read the sibling api modules as raw text through Vite rather than node:fs —
// the app tsconfig carries no Node types, and loosening it for one test is the
// wrong trade. `eager` keeps this synchronous so the helper below stays simple.
const API_SOURCES = import.meta.glob('./*.ts', { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

/**
 * Collect every mutating path declared across `api/*.ts` by reading the source.
 *
 * Source-scraped rather than hand-listed on purpose: a hand-list would itself
 * drift, and the whole point of this test is that adding an endpoint without an
 * invalidation rule fails CI instead of silently going stale.
 */
function declaredMutatingPaths(): { method: string; path: string }[] {
  const found: { method: string; path: string }[] = []
  for (const [file, text] of Object.entries(API_SOURCES)) {
    if (file.includes('.test.')) continue
    // `method` and `path` appear in both orders across these modules.
    const patterns = [
      /method:\s*'([A-Z]+)'[^}]*?path:\s*[`'"]([^`'"]+)/gs,
      /path:\s*[`'"]([^`'"]+)[^}]*?method:\s*'([A-Z]+)'/gs,
    ]
    patterns.forEach((re, i) => {
      for (const m of text.matchAll(re)) {
        const method = (i === 0 ? m[1] : m[2])!
        const raw = (i === 0 ? m[2] : m[1])!
        if (method === 'GET') continue
        // Substitute template holes with a plausible id segment.
        const path = raw.replace(/\$\{[^}]+\}/g, 'abc123')
        found.push({ method, path })
      }
    })
  }
  return found
}

describe('cache invalidation registry', () => {
  it('finds the mutating paths it is meant to police', () => {
    // Guards the scraper itself: if the api modules change shape and this
    // returns nothing, every other assertion here would vacuously pass.
    expect(declaredMutatingPaths().length).toBeGreaterThan(50)
  })

  it('has a rule for every mutating path in the api layer', () => {
    const unmapped = declaredMutatingPaths()
      .filter(({ path }) => !ruleForPath(path))
      .map(({ method, path }) => `${method} ${path}`)
    // Sorted + deduped so a failure reads as a to-do list.
    expect([...new Set(unmapped)].sort()).toEqual([])
  })

  it('ignores GET requests', () => {
    // Reads must never trigger invalidation — that is how you get a refetch loop.
    expect(ruleForPath('/v1/containers')).toBeDefined()
    // The method gate lives in client.ts; this asserts the rule table itself is
    // path-only and carries no method conditions that could mask that.
    for (const rule of INVALIDATION_RULES) {
      expect(Object.keys(rule)).toEqual(['test', 'roots'])
    }
  })

  it('strips the query string before matching', () => {
    expect(ruleForPath('/v1/containers?limit=20')).toBe(ruleForPath('/v1/containers'))
  })

  it('matches the most specific rule first', () => {
    // Sub-resources must not be swallowed by their parent prefix.
    expect(ruleForPath('/v1/claims/seized-items/abc')?.roots).toEqual(
      expect.arrayContaining([['seized-items']]),
    )
    expect(ruleForPath('/v1/claims/missing-items/abc')?.roots).toEqual(
      expect.arrayContaining([['missing-items']]),
    )
    expect(ruleForPath('/v1/billing/disputes/abc/resolve')?.roots).toEqual(
      expect.arrayContaining([['disputes']]),
    )
    expect(ruleForPath('/v1/tenant/container-capacities/abc')?.roots).toEqual([
      ['container-capacities'],
    ])
  })

  it('invalidates containers AND packing lists when a container changes', () => {
    // The reported bug: deleting a container left it in the cached list, and its
    // packing lists are freed by the same action.
    const roots = ruleForPath('/v1/containers/abc')?.roots
    expect(roots).toEqual(expect.arrayContaining([['containers'], ['packing-lists']]))
  })

  it('invalidates containers and billing when a packing list is approved', () => {
    // Approval consumes container CBM and can generate billing, neither of which
    // the request path mentions.
    const roots = ruleForPath('/v1/packing-lists/abc/approve')?.roots
    expect(roots).toEqual(
      expect.arrayContaining([['packing-lists'], ['containers'], ['billing']]),
    )
  })

  it('reaches the packing-list form and release notes when a warehouse changes', () => {
    // Both read the warehouse list — the arrival picker and the letterhead.
    const roots = ruleForPath('/v1/warehouses/abc/set-default')?.roots
    expect(roots).toEqual(
      expect.arrayContaining([['warehouses'], ['packing-lists'], ['release-notes']]),
    )
  })

  it('maps public pre-auth paths to no roots rather than leaving them unmapped', () => {
    // Nothing is cached before sign-in, but they must still MATCH, so the drift
    // test cannot be satisfied by an accidental catch-all later.
    for (const p of ['/v1/register/acme', '/v1/activate/tok', '/v1/invites/tok/accept', '/v1/onboarding-requests']) {
      expect(ruleForPath(p), p).toBeDefined()
      expect(ruleForPath(p)!.roots, p).toEqual([])
    }
  })

  it('has no rule whose roots are silently undefined', () => {
    // A typo'd key import would yield [undefined] and invalidate nothing.
    for (const rule of INVALIDATION_RULES) {
      for (const root of rule.roots) {
        expect(root, String(rule.test)).toBeDefined()
        expect(Array.isArray(root), String(rule.test)).toBe(true)
        expect(root.length, String(rule.test)).toBeGreaterThan(0)
      }
    }
  })
})
