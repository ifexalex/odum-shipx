/**
 * Drift guard: a `*Keys.list(...)` key belongs to its infinite-query hook.
 *
 * ## Why this exists
 *
 * `useCursorPagination` wraps `useInfiniteQuery`, which caches
 * `{ pages: ListResponse[], pageParams: unknown[] }`. A plain `useQuery` on the
 * same key caches a bare `ListResponse`. React Query has one cache entry per
 * key, so whichever mounts first writes its shape and the other reads garbage:
 * the infinite consumer finds `data.pages` undefined and throws.
 *
 * This shipped twice in master plan 7.150 before CI caught it:
 *
 * - `MyShipments`/`MyShipmentDetail` plain-queried `billingKeys.list({})`, which
 *   `useBillingList()` owns. Navigating `/my-shipments` -> `/my-billing` crashed
 *   `MyBilling` with no `<main>` at all.
 * - `WarehouseDashboard` plain-queried `releaseNoteKeys.list({status:'active'})`,
 *   the exact key `ReleaseNoteList` produces with its Active filter.
 *
 * Both now use the `lookup()` slots instead. Rather than rely on params never
 * coinciding, this test keeps flat reads out of the `list()` namespace entirely:
 * only `src/hooks/` may name a `list()` key as a `queryKey`.
 */
import { describe, expect, it } from 'vitest'
import * as keys from './keys'

// Vite's raw glob, the same mechanism api/cacheInvalidation.test.ts uses to
// scan sources. Deliberately not node:fs — the app tsconfig carries no node
// types, so a `node:fs` import fails `tsc -b` even though vitest runs it.
const ALL_SOURCES = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** `queryKey: fooKeys.list(...)` — the pattern that must stay inside hooks/. */
const LIST_AS_QUERY_KEY = /queryKey:\s*(\w+Keys)\.list\(/g

/**
 * The domains whose `list()` key is owned by an infinite query, derived from
 * `src/hooks/` rather than hard-coded, so adding a new paginated hook extends
 * this guard automatically.
 *
 * Domains with no infinite hook (e.g. `containerCapacityKeys`, a plain-array
 * endpoint) are not in scope: for them `list()` is the only slot and a plain
 * `useQuery` on it is correct.
 */
function infiniteOwnedDomains(): Set<string> {
  const owned = new Set<string>()
  for (const [path, text] of Object.entries(ALL_SOURCES)) {
    if (!path.includes('/hooks/')) continue
    for (const m of text.matchAll(/useCursorPagination[\s\S]{0,120}?(\w+Keys)\.list\(/g)) {
      owned.add(m[1]!)
    }
  }
  return owned
}

describe('query key ownership', () => {
  it('only src/hooks may use an infinite-owned *Keys.list() key as a queryKey', () => {
    const owned = infiniteOwnedDomains()
    expect(owned.size).toBeGreaterThan(5) // the derivation itself still works
    const offenders: string[] = []

    for (const [path, text] of Object.entries(ALL_SOURCES)) {
      // The infinite-query hooks are the legitimate owners of list() keys.
      if (path.includes('/hooks/') || /\.test\.tsx?$/.test(path)) continue

      for (const match of text.matchAll(LIST_AS_QUERY_KEY)) {
        if (!owned.has(match[1]!)) continue
        offenders.push(`${path} -> ${match[1]}.list(...)`)
      }
    }

    // A flat one-shot read belongs on that domain's lookup() slot; see the
    // header above for the two crashes this prevents.
    expect(offenders).toEqual([])
  })

  it('lookup() and list() never produce the same key for the same params', () => {
    const params = { status: 'active' }
    const withLookup = [
      keys.billingKeys,
      keys.packingListKeys,
      keys.claimKeys,
      keys.releaseNoteKeys,
    ]

    for (const factory of withLookup) {
      expect(factory).toHaveProperty('lookup')
      const lookup = JSON.stringify(factory.lookup(params))
      const list = JSON.stringify(factory.list(params))
      expect(lookup).not.toEqual(list)
    }
  })

  it('lookup() stays under all, so automatic invalidation still reaches it', () => {
    // api/cacheInvalidation.ts invalidates roots, not exact keys. A lookup key
    // outside its domain root would never be refreshed after a write.
    for (const factory of [keys.billingKeys, keys.packingListKeys, keys.claimKeys, keys.releaseNoteKeys]) {
      const root = factory.all as readonly unknown[]
      expect(factory.lookup({}).slice(0, root.length)).toEqual([...root])
    }
  })
})
