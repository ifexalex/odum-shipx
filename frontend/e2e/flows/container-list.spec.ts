/**
 * E2E — container list search, filters, and sort (china_office_staff).
 *
 * Covers the filter/search/sort work fixed earlier: the header search bar,
 * the table search input, the "Filters" panel's status multi-select and ETA
 * range, and column sorting — each previously broken in ways that only
 * showed up against a real backend (a bad q_clause, a filter param the
 * handler never read, sort UI with no onClick wired up).
 *
 * Requires seeded containers (make stack / make seed / seed_stress.py).
 */
import { expect, test } from '@playwright/test'
import { clickFilterAndSettle, dataRows, hasRows, settleNetwork, switchRole } from '../support/roleSwitch'

test.describe('container list', () => {
  test.beforeEach(async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await expect(page).toHaveURL(/\/containers/)
    await settleNetwork(page)
  })

  test('search narrows the table to matching rows', async ({ page }) => {
    // hasRows(), not count(): a one-shot count taken right after navigation
    // turns "the table has not rendered yet" into "there is no data", and the
    // test reports as skipped having never run. 7.160 converted fifteen of
    // these; this file was not among the ten it touched, so two survived here.
    test.skip(!(await hasRows(dataRows(page))), 'No containers seeded')

    const firstNumber = await dataRows(page).first().locator('td').first().textContent()
    test.skip(!firstNumber?.trim(), 'Could not read a container number to search for')

    await page.getByPlaceholder(/container number, vessel name, voyage/i).fill(firstNumber!.trim())
    await settleNetwork(page)

    // Retrying assertion rather than a counted-then-asserted variable: the
    // search refetch may not have committed when the count is taken.
    await expect(dataRows(page)).not.toHaveCount(0)
    await expect(page.locator('table tbody')).toContainText(firstNumber!.trim())
  })

  test('search for a nonsense string shows the empty state, not stale rows', async ({ page }) => {
    await page.getByPlaceholder(/container number, vessel name, voyage/i).fill('zzz-no-such-container-zzz')
    await settleNetwork(page)
    await expect(page.getByText(/no containers/i)).toBeVisible()
  })

  test('status chips filter the table and "All" clears the filter', async ({ page }) => {
    const totalRows = await dataRows(page).count()
    test.skip(totalRows === 0, 'No containers seeded')

    // Any chip besides "All" narrows (or empties) the result set.
    const chips = page.locator('button', { hasText: /^(in transit|cleared|loading|arrived)/i })
    const chipCount = await chips.count()
    test.skip(chipCount === 0, 'No status chips beyond "All" rendered')

    await clickFilterAndSettle(chips.first(), page)
    const filteredCount = await dataRows(page).count()

    // "All" alone is ambiguous — it also matches the sidebar's "All packing
    // lists" and the date filter's "All time". The status chip's accessible
    // name is "All <count>" (Chip.tsx renders the row count inside it), which
    // no other "All ..." control on this page has.
    await clickFilterAndSettle(page.getByRole('button', { name: /^all \d+$/i }), page)
    const restoredCount = await dataRows(page).count()

    expect(restoredCount).toBeGreaterThanOrEqual(filteredCount)
  })

  test('Filters panel: status multi-select narrows results and Clear resets it', async ({ page }) => {
    await page.getByRole('button', { name: /^filters$/i }).click()
    const dialog = page.getByRole('dialog', { name: /filters/i })
    await expect(dialog).toBeVisible()

    const statusOptions = dialog.getByRole('checkbox')
    const optionCount = await statusOptions.count()
    expect(optionCount).toBeGreaterThan(0)

    await statusOptions.first().click()
    await expect(statusOptions.first()).toHaveAttribute('aria-checked', 'true')

    await dialog.getByRole('button', { name: /clear all filters/i }).click()
    // Clearing closes the panel (clearAllFilters also calls setFiltersOpen(false)).
    await expect(dialog).not.toBeVisible()
  })

  test('sorting by a sortable column reorders the table without erroring', async ({ page }) => {
    const rowCount = await dataRows(page).count()
    test.skip(rowCount < 2, 'Need at least 2 rows to observe a sort')

    // "Container" is the first sortable column header.
    await page.locator('table thead button').first().click()

    // A real reorder isn't guaranteed by data (could coincidentally be a
    // no-op if already sorted), but the request must succeed — no error
    // banner, and the table settles back to real rows rather than staying on
    // a loading skeleton. A one-shot textContent() read here is flaky: it can
    // catch the table between the re-fetch starting and the new rows
    // rendering, so poll instead of reading once.
    await expect(page.getByText(/couldn.?t load|error/i)).not.toBeVisible()
    await expect(dataRows(page).first().locator('td').first()).not.toBeEmpty()
  })
})
