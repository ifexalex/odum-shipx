import type { Locator, Page } from '@playwright/test'

/**
 * Switch the local dev auth shim's active identity and wait for it to take
 * effect before interacting further.
 *
 * `#local-role-switcher`'s onChange updates LocalRoleContext asynchronously;
 * proceeding immediately can still act under the old role, so callers that
 * read `session.role` right after switching (RoleGuard included) may see a
 * stale value without this wait.
 */
export async function switchRole(page: Page, role: string): Promise<void> {
  await page.goto('/')
  await page.selectOption('#local-role-switcher', role)
  await page.waitForTimeout(200)
  await suppressRoleSwitcherOverlay(page)
}

/**
 * Disable pointer events on the floating dev role-switcher panel.
 *
 * It is `position: fixed; bottom; right; z-index: 2000` (RoleSwitcher.module.css)
 * — deliberately on top of everything so a role can be flipped from any
 * screen. That means it can sit directly over real page buttons near the
 * bottom-right corner; a click there is delivered by the browser to whatever
 * element is topmost at those coordinates, which is silently the switcher,
 * not the button underneath — no error, the click just never reaches its
 * target. `switchRole()` calls this automatically once the role is set, since
 * most tests don't need to touch the switcher again afterward. Call it again
 * manually only if a test switches role more than once.
 */
export async function suppressRoleSwitcherOverlay(page: Page): Promise<void> {
  await page.addStyleTag({ content: '#dev-role-switcher-panel { pointer-events: none; }' })
}

/**
 * Navigate to `path` **within the SPA** by clicking a nav link, rather than
 * `page.goto()`.
 *
 * The dev identity lives only in React state (LocalAuthProvider), with
 * nothing to persist it across a reload. `page.goto()` is a real browser
 * navigation — it reloads the page, which remounts the provider back to its
 * default identity (`platform_admin`) and silently undoes any prior
 * `switchRole()`. This bit packing-list.spec.ts: it switched to
 * china_office_staff, then called `page.goto('/packing-lists')`, which
 * reloaded the app back to platform_admin and got redirected to
 * /platform/dashboard by RoleGuard before the test's assertions ran.
 *
 * Use this for any navigation that must happen after `switchRole()`. Going
 * straight to a route with `page.goto()` is still fine as the *first*
 * navigation in a test, before any role switch.
 */
export async function goToViaNav(page: Page, linkName: string | RegExp): Promise<void> {
  // Sidebar nav items (src/shell/Sidebar.tsx) render as <button onClick=...>,
  // not <a>, so they carry the "button" accessible role rather than "link".
  await page.getByRole('button', { name: linkName }).first().click()
  await settleNetwork(page)
  await waitForTableSettled(page)
}

/**
 * Best-effort "no requests in flight" wait — never fatal.
 *
 * `waitForLoadState('networkidle')` needs 500ms in which THIS page has no
 * network activity, and scripts/local_server.py runs `threaded=False` on
 * purpose (shared/db.py's connection singleton is not thread-safe, and one
 * request at a time is the faithful match to Lambda). So the whole API
 * serializes: with Playwright's four workers all driving it, a page's own
 * requests can stay pending long enough that no idle window ever opens, and
 * a bare networkidle wait then throws at 30s.
 *
 * That is exactly how it failed: four tests in billing-payment-and-release
 * and bulk-packing-list-actions died on this line — never on an assertion —
 * purely because they ran while three other workers had the server busy.
 *
 * So treat settling as an optimization, not a precondition: wait briefly, and
 * on timeout carry on. Correctness still comes from Playwright's auto-waiting
 * assertions and from waitForTableSettled()'s aria-busy check, neither of
 * which cares how busy other workers are. Playwright's own docs discourage
 * networkidle for this reason.
 */
export async function settleNetwork(page: Page, timeout = 5_000): Promise<void> {
  await page.waitForLoadState('networkidle', { timeout }).catch(() => {
    // Server busy serving other workers — not this test's problem.
  })
}

/**
 * Click a filter/chip control and wait past the react-query settle race, not
 * just network completion.
 *
 * `waitForLoadState('networkidle')` guarantees no in-flight XHR — it says
 * nothing about whether the resulting query cache update has actually
 * committed to the DOM. Reading row state (a count, a checkbox click)
 * immediately after can observe the *previous* filter's data: a "Draft"
 * filter's row count read before the commit lands still sees the old
 * "pending_approval" rows, so a `rowCount === 0` skip never fires and the
 * test hangs waiting for a checkbox that belongs to a row about to disappear.
 * Reproduced directly and consistently fixed by a brief wait after settling —
 * there is no DOM signal to poll for instead, since the "loading" state and
 * the final state can look identical (same table, different row count).
 */
export async function clickFilterAndSettle(locator: Locator, page: Page): Promise<void> {
  await locator.click()
  await settleNetwork(page)
  await waitForTableSettled(page)
}

/**
 * Wait until the table is no longer loading.
 *
 * There IS a DOM signal (contrary to what this file used to claim): Table.tsx
 * sets `aria-busy` on the <table> and marks its placeholder rows
 * `data-skeleton-row`. Waiting on aria-busy="false" is exact, where the old
 * fixed 300ms wait was a guess that could be both too short and wasteful.
 *
 * Why this matters, concretely: the skeleton is five full-width rows, so a row
 * count taken mid-load returns 5 regardless of the real data. That is what
 * made container-list.spec.ts fail against a local stack holding only two
 * containers — it read `filteredCount` as 5 while the filter was still in
 * flight (the true filtered count was 0), then compared it against the
 * correctly-restored 2 and failed `restored >= filtered`. `dataRows()` now
 * excludes skeleton rows, so a stray count can no longer be inflated this way.
 *
 * The narrow (card) layout has no table; the aria-busy wait simply no-ops
 * there, which is correct — the card list has no row-count assertions.
 */
export async function waitForTableSettled(page: Page): Promise<void> {
  const table = page.locator('table[aria-busy="false"]').first()
  await table.waitFor({ state: 'attached', timeout: 10_000 }).catch(() => {
    // No table on the page (card layout, or an empty state rendered without
    // one) — nothing to settle. Never fail a test for the absence of a table.
  })
}

/**
 * `table tbody tr` for an empty list — Table.tsx renders the empty state as a
 * real single-cell <tr colSpan=...>, not an absence of rows. Counting or
 * indexing plain `tbody tr` treats that row as data: `rowCount === 0` never
 * triggers, and `.first()` finds a row with no cells the test expects
 * (checkbox, "View" button, ...), producing a 30s timeout instead of a clean
 * skip. Scope to rows with more than one cell instead.
 *
 * Loading placeholders are excluded for the same reason: Table.tsx renders
 * five skeleton <tr>s with a full set of <td>s while a query is in flight, so
 * without `:not([data-skeleton-row])` any count taken mid-load returns 5 —
 * real-looking, and wrong. See waitForTableSettled().
 */
export function dataRows(page: Page): Locator {
  return page
    .locator('table tbody tr:not([data-skeleton-row])')
    .filter({ has: page.locator('td:nth-child(2)') })
}
