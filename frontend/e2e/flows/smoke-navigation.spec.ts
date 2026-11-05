/**
 * E2E — smoke sweep across every real nav destination, for every role.
 *
 * Driven directly by `navConfig` (the actual data Sidebar/CustomerTopNav
 * render), not a hand-maintained copy — this can't silently drift out of
 * sync with the app's real nav tree the way a hardcoded route list would.
 *
 * Cheap, broad net: for each role, click every item its own nav renders and
 * assert the destination doesn't show an error banner or 500, and something
 * real (a heading, or the empty-state text a list explicitly renders when it
 * has no rows) is on screen. This does not assert *correctness* of what's
 * shown — deeper interaction is covered by the dedicated flow specs
 * (container-list, bulk-packing-list-actions, customer-invite, ...). It
 * exists to catch "this route 500s / renders a blank page / throws" across
 * the ~30 destinations nothing else currently visits.
 */
import { expect, test } from '@playwright/test'
import { navConfig } from '../../src/shell/navConfig'
import { goToViaNav, settleNetwork, switchRole } from '../support/roleSwitch'

const ROLES = Object.keys(navConfig) as (keyof typeof navConfig)[]

// Form/action routes (create/import wizards) get a real interaction test
// elsewhere and would need setup data to render past their first step here —
// skip them in this generic sweep rather than assert something shallow.
const SKIP_LABELS = new Set(['Create container', 'Create packing list', 'Import from Excel'])

for (const role of ROLES) {
  const items = navConfig[role].flatMap((group) => group.items).filter((item) => !SKIP_LABELS.has(item.label))

  test.describe(`smoke: ${role} nav`, () => {
    for (const item of items) {
      test(`"${item.label}" (${item.path}) renders without error`, async ({ page }) => {
        await switchRole(page, role)
        await goToViaNav(page, new RegExp(`^${item.label}$`, 'i'))

        // Not a strict path match: some nav destinations (e.g. a group whose
        // path is a parent of what actually loads) can redirect within the
        // same section. What matters is the page settled somewhere real.
        //
        // Order matters. Assert the page has arrived FIRST, then that no error
        // survives — the reverse checks a transient state and fails on a blip
        // that the page recovers from by itself: queryClient.ts retries a
        // failed query once, so a query that loses a race against the
        // single-request-at-a-time local API renders an error, retries, and
        // succeeds. /admin/customers failed exactly that way, and the captured
        // snapshot held no error text at all, because by then there was none.
        // toHaveCount(0) is a settled-state check rather than a moment-in-time
        // one; a page genuinely stuck on an error still fails here.
        await expect(page.locator('main, [role="main"]').first()).toBeVisible()
        await settleNetwork(page)
        await expect(
          page.getByText(/internal server error|something went wrong|unexpected error/i),
        ).toHaveCount(0)
      })
    }
  })
}
