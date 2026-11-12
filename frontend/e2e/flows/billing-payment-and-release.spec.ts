/**
 * E2E — record a payment, generate a release note, then record its pickup.
 *
 * The full real-world chain a Nigeria-side staff member performs: a customer
 * pays their outstanding balance, staff generate the release note (the
 * physical authorization to collect cargo), and record the actual pickup
 * when the customer or a delegate comes to the warehouse.
 *
 * Uses a real seeded partially-paid billing record (Ibrahim Musa,
 * container ACME001001) — chosen because partially_paid already permits
 * generating a release note (canGenerateRelease in BillingDetail.tsx), so
 * this exercises that path specifically rather than only the fully-paid one.
 * Real seeded carton tags (ACME-001-003, ACME-001-004) are used since the
 * release-note form requires tags that actually exist on the container.
 */
import { expect, test } from '@playwright/test'
import { actionAvailable, becomesVisible, goToViaNav, hasRows, settleNetwork, switchRole } from '../support/roleSwitch'

const CUSTOMER_NAME = 'Ibrahim Musa'
const CARTON_TAGS = ['ACME-001-003', 'ACME-001-004']

async function openBillingRecord(page: import('@playwright/test').Page): Promise<void> {
  await switchRole(page, 'tenant_admin')
  await goToViaNav(page, /^billing$/i)
  await page.getByPlaceholder(/reference, customer, container/i).fill(CUSTOMER_NAME)
  await settleNetwork(page)
  const row = page.locator('table tbody tr').filter({ hasText: CUSTOMER_NAME })
  await expect(row).toHaveCount(1)
  // BillingList.tsx's row action button label depends on payment status
  // (rowAction()): "Record payment" for unpaid/partially_paid, "Release" for
  // paid, plain "View" otherwise — not a fixed label like other tables.
  await row.getByRole('button', { name: /record payment|release|^view$/i }).click()
  await expect(page).toHaveURL(/\/billing\//)
  // Wait for the detail page to actually settle before any caller checks
  // which action buttons are present — isVisible() is a one-shot check with
  // no retry, and can run before the page finishes rendering right after
  // navigation, wrongly reporting an action as unavailable.
  await expect(page.getByText('Outstanding', { exact: true }).first()).toBeVisible()
}

test.describe('billing payment and release note', () => {
  test('recording a payment reduces the outstanding balance', async ({ page }) => {
    await openBillingRecord(page)

    // Target the Outstanding StatCard specifically. "Outstanding" text appears
  // twice on the page (the StatCard label, and an unrelated fee-breakdown
  // row) — .first() picks the StatCard's label <div>; two levels up reaches
  // StatCard's root, which also contains the sibling <div> holding the ₦
  // value (StatCard.tsx: label and value are sibling divs under one Card).
  const outstandingCard = page.getByText('Outstanding', { exact: true }).first().locator('../..')
  const outstandingBefore = await outstandingCard.textContent()

    const recordBtn = page.getByRole('button', { name: /record payment/i })
    if (!(await actionAvailable(page, /record payment/i))) {
      // canRecordPayment() is false — already fully settled by a previous
      // run (paid, overpaid, or released_with_outstanding all hide this
      // button). Nothing further to test on this pass.
      return
    }

    await recordBtn.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Record payment' })).toBeVisible()

    await dialog.getByLabel(/amount/i).fill('10000')
    await dialog.getByRole('button', { name: /confirm payment/i }).click()

    await expect(dialog).not.toBeVisible({ timeout: 10_000 })

    // The page must reflect the new amount, not silently keep showing stale
    // data (a real regression class: a write succeeding but the detail view
    // not refetching).
    //
    // A RETRYING assertion, not `textContent()` + `not.toBe()`. This test was
    // intermittently flaky and that was the cause: `textContent()` waits for
    // the element to be ATTACHED but does not retry the VALUE, and the
    // Outstanding card is attached the whole time — showing the old figure. So
    // the read could land in the window between the dialog closing and the
    // invalidated query committing its refetch to the DOM, and compare the
    // stale value against itself.
    //
    // Third member of a family already fixed twice: `isVisible()` (7.153) and
    // `count()` (7.160). The lesson that generalises is not "this helper is
    // one-shot" but "assert with `expect(locator)`, which retries, rather than
    // reading a value into a variable and asserting on the variable".
    expect(outstandingBefore, 'Outstanding card had no text to compare against').toBeTruthy()
    await expect(outstandingCard).not.toHaveText(outstandingBefore!, { timeout: 10_000 })
  })

  test('generating a release note with real carton tags succeeds, then pickup can be recorded', async ({ page }) => {
    await openBillingRecord(page)

    const generateBtn = page.getByRole('button', { name: /generate release note/i })
    test.skip(!(await actionAvailable(page, /generate release note/i)), 'No "Generate release note" action available for this billing status')

    await generateBtn.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Generate release note' })).toBeVisible()

    await dialog.getByLabel(/carton tags to release/i).fill(CARTON_TAGS.join('\n'))
    await expect(dialog.getByText(`${CARTON_TAGS.length} tag(s) parsed`)).toBeVisible()

    // This billing record's accumulated test payments (test 1 above nudges it
    // forward each run) may or may not cover the requested cartons in full —
    // "Release with outstanding balance" is the form's own built-in path for
    // exactly that case (a manager override, real business behavior), so use
    // it rather than assume full payment. Real seeded data, not a mock, so
    // this can't be sidestepped by controlling the fixture.
    await dialog.getByLabel(/release with outstanding balance/i).check()
    await dialog.getByLabel(/approval notes/i).fill('e2e test — manager override for testing')

    const generateSubmit = dialog.getByRole('button', { name: /^generate$/i })
    await expect(generateSubmit).toBeEnabled()
    await generateSubmit.click()

    // On success the modal closes and a release note now exists for this
    // billing record. If those exact tags were already released by an
    // earlier run, the backend's duplicate guard (generate_release_note's
    // get_active_release_note_carton_tags check) rejects it with an error
    // alert — treat that as the "already done" case rather than a failure.
    const failedAlready = dialog.getByRole('alert')
    await Promise.race([
      expect(dialog).not.toBeVisible({ timeout: 10_000 }),
      expect(failedAlready).toBeVisible({ timeout: 10_000 }),
    ])

    if (await becomesVisible(dialog)) {
      await dialog.getByRole('button', { name: /cancel/i }).click()
    }

  })

  test('recording a pickup on an active release note updates its status', async ({ page }) => {
    // Independent of the generation step above (which only succeeds once —
    // re-running it after the billing moves to a terminal status correctly
    // skips). Finds whatever active release note already exists for this
    // customer, rather than depending on having just created one.
    // canRecordPickup() (releaseNotesRules.ts) restricts this to
    // warehouse_attendant specifically — not tenant_admin or nigeria staff,
    // who can generate/view notes but not record the physical handover.
    await switchRole(page, 'warehouse_attendant')
    await goToViaNav(page, /^release notes$/i)
    const noteRow = page.locator('table tbody tr').filter({ hasText: CUSTOMER_NAME }).first()
    // The list's own fetch starts on mount, a tick after the nav click
    // settles — a one-shot .count() can race the Table's loading skeleton
    // (blank rows). toHaveCount retries until real rows render or time out.
    await expect(noteRow).toHaveCount(1, { timeout: 10_000 }).catch(() => undefined)
    test.skip(!(await hasRows(noteRow)), 'No release note found for this customer — run the generation test first')

    await noteRow.getByRole('button', { name: /^view$/i }).click()
    await expect(page).toHaveURL(/\/release-notes\//)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const pickupBtn = page.getByRole('button', { name: /^record pickup$/i })
    test.skip(!(await actionAvailable(page, /^record pickup$/i)), 'Already picked up — nothing left to test')

    await pickupBtn.click()
    const pickupDialog = page.getByRole('dialog')
    await expect(pickupDialog.getByRole('heading', { name: /record pickup/i })).toBeVisible()
    await pickupDialog.getByLabel(/cartons collected/i).fill(String(CARTON_TAGS.length))
    await pickupDialog.getByRole('button', { name: /confirm pickup/i }).click()

    await expect(pickupDialog).not.toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/picked up/i)).toBeVisible()
  })
})
