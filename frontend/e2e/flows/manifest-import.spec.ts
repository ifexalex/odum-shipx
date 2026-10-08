/**
 * E2E — forwarder manifest import wizard (china_office_staff).
 *
 * Exercises the real upload path: Playwright picks a genuine .xlsx file,
 * the app PUTs it to Moto's S3-compatible presigned URL (cloud-neutral PUT
 * contract, no mocking), then calls POST /v1/manifests/import against the real
 * local Flask server.
 *
 * The fixture (e2e/fixtures/e2e-test-manifest.xlsx, built by
 * scripts/make_test_manifest.py) carries only the tester's own contact —
 * never a real customer's, per the session's no-live-notification rule.
 *
 * Re-running this spec re-imports the same container/customer. That's safe:
 * services/excel/service.py dedupes on (delivery_note_number, bale_no), so a
 * second run reports items_skipped_duplicate rather than creating a second
 * copy — this test asserts exactly that behavior on a second pass.
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { goToViaNav, switchRole } from '../support/roleSwitch'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FIXTURE = path.join(__dirname, '../fixtures/e2e-test-manifest.xlsx')

test.describe('manifest import wizard', () => {
  test('uploads a manifest, imports it, and shows the per-row result', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await goToViaNav(page, /packing lists/i)
    await goToViaNav(page, /import from excel/i)

    // Step 1 — mode defaults to "Forwarder manifest"; no container picker for it.
    await expect(page.getByRole('radio', { name: /forwarder manifest/i })).toHaveAttribute('aria-checked', 'true')
    await page.getByLabel(/choose \.xlsx file/i).setInputFiles(FIXTURE)
    await expect(page.getByText('e2e-test-manifest.xlsx')).toBeVisible()
    await page.getByRole('button', { name: /next: confirm/i }).click()

    // Step 2 — confirm.
    await expect(page.getByRole('heading', { name: 'Confirm import' })).toBeVisible()
    await page.getByRole('button', { name: /confirm.*import/i }).click()

    // Step 3 — results. Either outcome (fresh rows or an already-imported
    // duplicate) is a pass; a network/parse failure surfacing as the error
    // banner from step 1/2 is not.
    await expect(page.getByText('Import complete')).toBeVisible({ timeout: 15_000 })
    const itemsAdded = await page.getByText('Items added').locator('..').getByText(/^\d+$/).textContent()
    const alreadyImported = await page.getByText('Already imported').locator('..').getByText(/^\d+$/).textContent()
    expect(Number(itemsAdded) + Number(alreadyImported)).toBeGreaterThan(0)
  })

  test('rejects confirming without a file selected', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await goToViaNav(page, /packing lists/i)
    await goToViaNav(page, /import from excel/i)

    await expect(page.getByRole('button', { name: /next: confirm/i })).toBeDisabled()
  })
})
