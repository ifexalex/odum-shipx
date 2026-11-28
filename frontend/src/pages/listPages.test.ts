/**
 * FD-18: every list page uses the one layout (`ListPage`) and the one filter bar (`FilterBar`), so the order of a
 * list's parts and of its filters is the same everywhere. A page keeps no filter card or stats row of its own.
 */
import { describe, expect, it } from 'vitest'

const PAGES = import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

/** The staff list pages: a table of records, filtered. Settings tables and the customer's own cards are not. */
const LIST_PAGES = [
  './china/ContainerList.tsx',
  './china/PackingListList.tsx',
  './nigeria/BillingList.tsx',
  './nigeria/CarryoverLedger.tsx',
  './nigeria/ClaimList.tsx',
  './nigeria/DisputeList.tsx',
  './nigeria/ManifestList.tsx',
  './nigeria/MissingItemList.tsx',
  './nigeria/RefundList.tsx',
  './nigeria/ReleaseNoteList.tsx',
  './nigeria/SeizedItemList.tsx',
  './platform/OnboardingRequests.tsx',
  './platform/PlatformApprovals.tsx',
  './platform/PlatformAuditLog.tsx',
  './platform/PlatformTenantList.tsx',
  './tenant-admin/ActivityLog.tsx',
  './tenant-admin/AdminCustomerList.tsx',
  './tenant-admin/NotificationLog.tsx',
  './tenant-admin/StaffUserList.tsx',
]

describe('one list layout (FD-18)', () => {
  it.each(LIST_PAGES)('%s uses ListPage and FilterBar, and builds no filter card or stats row itself', (path) => {
    const source = PAGES[path]
    expect(source, `${path} is not a page`).toBeDefined()
    expect(source).toMatch(/<ListPage\b/)
    expect(source).toMatch(/<FilterBar\b/)
    expect(source).not.toMatch(/styles\.(statsRow|filterRow|filtersPanel|filtersWrap)\b/)
  })

  it('no page outside the list pages lays out a list by hand with ListPage’s parts', () => {
    const others = Object.entries(PAGES).filter(([path, source]) => !LIST_PAGES.includes(path) && /<FilterBar\b/.test(source))
    expect(others.map(([path]) => path)).toEqual([])
  })
})
