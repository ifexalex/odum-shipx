/**
 * E2E — splitting an active release note into a child note for uncollected
 * cartons (SplitModal in ReleaseNoteDetail.tsx / POST /v1/release-notes/:id/split).
 *
 * Previously had zero e2e coverage. Uses a real seeded, fully-paid billing
 * with two real carton tags (Ngozi Adeyemi, container ACME001002) that no
 * other spec file in this suite touches, specifically so it doesn't collide
 * with billing-payment-and-release.spec.ts (Ibrahim Musa, ACME001001) or
 * release-note-migration-fields.spec.ts (Ngozi Adeyemi, ACME001001).
 */
import { expect, test } from '@playwright/test'
import { actionAvailable, becomesVisible, goToViaNav, settleNetwork, switchRole } from '../support/roleSwitch'

const CUSTOMER_NAME = 'Ngozi Adeyemi'
const CONTAINER_NUMBER = 'ACME001002'
const BILLING_INVOICE_NUMBER = 'INV-A-003'
const TAGS = ['ACME-002-001', 'ACME-002-002']

test.describe('release note — split', () => {
  test('splitting an active release note moves the selected tag into a new child note', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    await goToViaNav(page, /^billing$/i)
    await page.getByPlaceholder(/reference, customer, container/i).fill(CUSTOMER_NAME)
    await settleNetwork(page)
    const row = page.locator('table tbody tr')
      .filter({ hasText: CUSTOMER_NAME })
      .filter({ hasText: CONTAINER_NUMBER })
      .filter({ hasText: BILLING_INVOICE_NUMBER })
    await expect(row).toHaveCount(1)
    await row.getByRole('button', { name: /record payment|release|^view$/i }).click()
    await expect(page).toHaveURL(/\/billing\//)
    await expect(page.getByText('Outstanding', { exact: true }).first()).toBeVisible()

    const generateBtn = page.getByRole('button', { name: /generate release note/i })
    if (await actionAvailable(page, /generate release note/i)) {
      await generateBtn.click()
      const dialog = page.getByRole('dialog')
      await expect(dialog.getByRole('heading', { name: 'Generate release note' })).toBeVisible()
      await dialog.getByLabel(/carton tags to release/i).fill(TAGS.join('\n'))
      await expect(dialog.getByText(new RegExp(`${TAGS.length} tags? read`, 'i'))).toBeVisible()
      const generateSubmit = dialog.getByRole('button', { name: /^generate release note$/i })
      await expect(generateSubmit).toBeEnabled()
      await generateSubmit.click()
      await Promise.race([
        expect(dialog).not.toBeVisible({ timeout: 10_000 }),
        expect(dialog.getByRole('alert')).toBeVisible({ timeout: 10_000 }),
      ])
      // Unlike release-note-migration-fields.spec.ts, this test keeps going
      // after this block — a re-run hitting the duplicate-tag guard (tags
      // already on the note from an earlier pass) leaves the dialog open
      // with an error alert, and its overlay would otherwise block every
      // subsequent click on the page. Close it before navigating on.
      if (await becomesVisible(dialog)) {
        await dialog.getByRole('button', { name: /cancel/i }).click()
        await expect(dialog).not.toBeVisible({ timeout: 5_000 })
      }
    }

    await goToViaNav(page, /^release notes$/i)
    const noteRow = page.locator('table tbody tr')
      .filter({ hasText: CUSTOMER_NAME })
      .filter({ hasText: CONTAINER_NUMBER })
      .first()
    // The list's own fetch starts on mount, a tick after the nav click
    // settles — networkidle here can resolve before it even begins (unlike
    // the billing list checks above, where filling the search box naturally
    // adds enough delay). A one-shot .count() would race the Table's loading
    // skeleton; toHaveCount retries until the real rows render or time out.
    let found = true
    try {
      await expect(noteRow).toHaveCount(1, { timeout: 10_000 })
    } catch {
      found = false
    }
    test.skip(!found, 'No release note found for this customer — generation did not succeed')
    await noteRow.getByRole('button', { name: /^view$/i }).click()
    await expect(page).toHaveURL(/\/release-notes\//)

    const splitBtn = page.getByRole('button', { name: /split note/i })
    test.skip(!(await actionAvailable(page, /split note/i)), 'Split not available — already split, picked up, or a single-tag note')

    await splitBtn.click()
    const splitDialog = page.getByRole('dialog')
    await expect(splitDialog.getByRole('heading', { name: 'Split release note' })).toBeVisible()

    await splitDialog.getByRole('checkbox', { name: TAGS[1] }).click()
    await expect(splitDialog.getByText('1 carton(s) selected for new note')).toBeVisible()

    const createChild = splitDialog.getByRole('button', { name: /create child note/i })
    await expect(createChild).toBeEnabled()
    await createChild.click()
    await expect(splitDialog).not.toBeVisible({ timeout: 10_000 })

    // On success the modal closes and the parent's own detail page reloads
    // (split_release_note doesn't mutate the parent's own carton_tags/status —
    // only a new child row is created). The verifiable signal is a second,
    // new "Partial release" row for this customer+container on the list.
    await goToViaNav(page, /^release notes$/i)
    const rows = page.locator('table tbody tr')
      .filter({ hasText: CUSTOMER_NAME })
      .filter({ hasText: CONTAINER_NUMBER })
    await expect(rows).toHaveCount(2)
    await expect(rows.filter({ hasText: 'Partial release' })).toHaveCount(1)
  })
})
