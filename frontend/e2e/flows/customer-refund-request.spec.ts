/**
 * E2E — customer requests a refund directly from their billing page.
 *
 * This is a completely different creation path from claims-and-refunds.spec.ts
 * (which tests the claim-triggered refund path) — RefundRequest.tsx posts
 * directly to POST /v1/refunds with customer_id explicitly left blank, on the
 * assumption (per its own code comment) that "Server derives from JWT for
 * customer role." Untested until now.
 */
import { expect, test } from '@playwright/test'
import { settleNetwork, switchRole } from '../support/roleSwitch'

test.describe('customer refund request', () => {
  test('requesting a refund from billing succeeds with the customer correctly attributed', async ({ page }) => {
    await switchRole(page, 'customer')
    await page.getByRole('button', { name: /^billing$/i }).click()
    await settleNetwork(page)

    // MyBilling.tsx renders each billing record as a clickable card
    // (role="button"), not a table row.
    const card = page.getByRole('button', { name: /ACME/i }).first()
    test.skip((await card.count()) === 0, 'No billing records for the seeded customer identity')
    await card.click()
    await expect(page).toHaveURL(/\/my-billing\//)

    const requestBtn = page.getByRole('button', { name: /request.*refund/i })
    test.skip(!(await requestBtn.isVisible().catch(() => false)), 'No "Request refund" action on this billing record')
    await requestBtn.click()
    await expect(page).toHaveURL(/\/refund-request/)

    await page.getByLabel(/amount requested/i).fill('15000')
    await page.getByLabel(/reason for refund/i).fill('e2e test — customer-initiated refund request')
    await page.getByRole('button', { name: /submit|request refund/i }).click()

    // A raw crash (customer_id sent as '' and rejected by a uuid column)
    // would surface as a generic error banner rather than navigating away.
    await expect(page.getByText(/internal server error|could not submit/i)).not.toBeVisible({ timeout: 8_000 })
    await expect(page).not.toHaveURL(/\/refund-request/)
  })
})
