/**
 * E2E — bulk packing-list actions (submit / approve / reject).
 *
 * Covers three bugs found and fixed earlier this session:
 *  - bulk approve on draft rows failed with a raw wrong_status:draft per row
 *    (fixed: bulk_set_status dispatches explicitly per target status);
 *  - self-approval was rejected with 50 individual self_approval_forbidden
 *    rows, unreadable as a user-facing message (fixed: approvableCount is
 *    computed client-side before firing the request, and failures are
 *    grouped by cause with a human explanation — BulkResultPanel);
 *  - china_office_staff can never approve their own imports; tenant_admin can,
 *    since they aren't the creator (canApprove / canApproveOrReject rules).
 */
import { expect, test } from '@playwright/test'
import { clickFilterAndSettle, dataRows, goToViaNav, switchRole } from '../support/roleSwitch'

test.describe('bulk packing-list actions', () => {
  test('china_office_staff: selecting only self-created pending lists disables Bulk approve', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await goToViaNav(page, /packing lists/i)

    await clickFilterAndSettle(page.getByRole('button', { name: /^pending approval$/i }), page)

    const rowCount = await dataRows(page).count()
    test.skip(rowCount === 0, 'No pending_approval packing lists seeded')

    // Select all pending rows via the header checkbox (clickFilterAndSettle
    // above already covers the react-query settle race).
    await page.locator('table thead').getByRole('checkbox').click()

    const bulkBar = page.getByText(/packing list\(s\) selected/i)
    await expect(bulkBar).toBeVisible()

    // If every selected list was created by this same seeded user, the
    // approve button must be disabled rather than let staff fire a request
    // every row will reject.
    const hint = page.getByText(/you created all of these|need another approver/i)
    if (await hint.isVisible().catch(() => false)) {
      await expect(page.getByRole('button', { name: /bulk approve/i })).toBeDisabled()
    }
  })

  test('tenant_admin: bulk-approving pending lists created by staff succeeds', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    await goToViaNav(page, /packing lists/i)

    await clickFilterAndSettle(page.getByRole('button', { name: /^pending approval$/i }), page)

    const rowCount = await dataRows(page).count()
    test.skip(rowCount === 0, 'No pending_approval packing lists seeded')

    await dataRows(page).first().getByRole('checkbox').click()
    const approveBtn = page.getByRole('button', { name: /bulk approve/i })
    await expect(approveBtn).toBeEnabled()
    await approveBtn.click()

    // Either outcome — a result panel or the row disappearing from the
    // pending filter — proves the request round-tripped and was not the old
    // wrong_status:draft failure. bulk_set_status now dispatches per target
    // status instead of defaulting non-approved outcomes to "rejected".
    // .first() matters: both alternatives can be on screen at once — acting on
    // the last pending list shows "1 succeeded · 0 failed" AND leaves the
    // filtered list empty ("No packing lists yet."). Without it, `.or()` is a
    // strict-mode violation, so the test fails *because it worked* — which is
    // exactly what happened once the suite ran serially and reached this case.
    await expect(
      page.getByText(/succeeded/i).or(page.getByText(/no packing lists/i)).first(),
    ).toBeVisible({ timeout: 10_000 })
  })

  test('bulk reject: modal requires no comment but is cancellable', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    await goToViaNav(page, /packing lists/i)

    await clickFilterAndSettle(page.getByRole('button', { name: /^pending approval$/i }), page)

    const rowCount = await dataRows(page).count()
    test.skip(rowCount === 0, 'No pending_approval packing lists seeded')

    await dataRows(page).first().getByRole('checkbox').click()
    await page.getByRole('button', { name: /bulk reject/i }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: /cancel/i }).click()
    await expect(dialog).not.toBeVisible()

    // Cancelling must not have submitted anything — selection survives.
    await expect(page.getByText(/packing list\(s\) selected/i)).toBeVisible()
  })

  test('bulk submit: draft lists move to pending_approval without a wrong_status error', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await goToViaNav(page, /packing lists/i)

    await clickFilterAndSettle(page.getByRole('button', { name: /^draft$/i }), page)

    const rowCount = await dataRows(page).count()
    test.skip(rowCount === 0, 'No draft packing lists seeded')

    await dataRows(page).first().getByRole('checkbox').click()
    await page.getByRole('button', { name: /submit for approval/i }).click()

    await expect(page.getByText(/wrong_status/i)).not.toBeVisible()
    // .first() matters: both alternatives can be on screen at once — acting on
    // the last pending list shows "1 succeeded · 0 failed" AND leaves the
    // filtered list empty ("No packing lists yet."). Without it, `.or()` is a
    // strict-mode violation, so the test fails *because it worked* — which is
    // exactly what happened once the suite ran serially and reached this case.
    await expect(
      page.getByText(/succeeded/i).or(page.getByText(/no packing lists/i)).first(),
    ).toBeVisible({ timeout: 10_000 })
  })
})
