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
  // addInitScript, not just addStyleTag: a style tag applies only to the
  // document currently loaded, and page.goto() is a real navigation that
  // throws it away. Several specs call switchRole() and then goto() a route,
  // which silently brought the overlay back — and a click landing on it is not
  // an error, it just never reaches the button underneath.
  //
  // That is how cbm-rate-config.spec.ts failed: after goto('/admin/config/
  // cbm-rate') the click on "Naira (₦)" went to the switcher instead, so the
  // currency never changed and the test timed out waiting for the ₦ labels —
  // while the per-type labels it had already asserted were present in $.
  // addInitScript re-runs on every navigation, so the suppression persists.
  await page.addInitScript((css: string) => {
    const inject = (): void => {
      const el = document.createElement('style')
      el.textContent = css
      document.head.appendChild(el)
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', inject, { once: true })
    } else {
      inject()
    }
  }, OVERLAY_SUPPRESSION_CSS)
  // Also apply to the page as it stands right now, since addInitScript only
  // takes effect from the next navigation onward.
  await page.addStyleTag({ content: OVERLAY_SUPPRESSION_CSS }).catch(() => {
    // No document yet (nothing navigated) — the init script will cover it.
  })
}

const OVERLAY_SUPPRESSION_CSS = '#dev-role-switcher-panel { pointer-events: none !important; }'

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
  // Bail out immediately when the page has no table at all — card layout, or a
  // route that simply isn't a list. count() resolves right away rather than
  // waiting, which matters: waiting for `table[aria-busy="false"]` to attach on
  // a page that will never have one burns the whole timeout on every single
  // navigation. That alone pushed smoke-navigation.spec.ts past Playwright's
  // 30s per-test limit and stretched the file from seconds to ~5 minutes.
  if ((await page.locator('table').count()) === 0) return

  await page.locator('table[aria-busy="false"]').first()
    .waitFor({ state: 'attached', timeout: 10_000 })
    .catch(() => {
      // Still loading after 10s — leave it to the caller's own assertions,
      // which auto-wait. Never fail a test merely for a slow table.
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

/**
 * Is a page action genuinely unavailable, or has it simply not rendered yet?
 *
 * `locator.isVisible()` is a ONE-SHOT check with no retry. Several specs used it
 * directly inside `test.skip(...)`, which silently turned "the page had not
 * finished rendering" into "this action does not apply" — so the test reported
 * as skipped and never ran. On a freshly seeded stack that hid real coverage:
 * the whole release-note chain skipped because the first test in it gave up
 * before the action row rendered.
 *
 * Waiting for a settle marker is not enough either. On the billing detail page
 * the unconditional Export button becomes visible BEFORE the conditional
 * actions beside it, so waiting on Export still reported "Generate release
 * note" as missing when it appeared ~instants later.
 *
 * This waits for the action itself and only then answers. When the action
 * really is unavailable the caller pays `timeout` once before skipping, which
 * is the right trade: a slow skip is cheap, a false skip is invisible lost
 * coverage.
 */
export async function actionAvailable(
  page: import('@playwright/test').Page,
  name: RegExp,
  timeout = 7_000,
): Promise<boolean> {
  const button = page.getByRole('button', { name }).first()
  try {
    await button.waitFor({ state: 'visible', timeout })
    return true
  } catch {
    return false
  }
}
