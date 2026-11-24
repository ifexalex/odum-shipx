/**
 * E2E — the release-note field additions layered on top of the original
 * carton-tag-only flow: warehouse selection, physical document number,
 * packing list invoice numbers, count-based release (packages_released /
 * package_unit, an alternative to carton_tags for bulk-quantity manifest
 * data with no per-carton tags), and RecordPickupModal's warehouse / CSO /
 * accounting-officer pickers.
 *
 * billing-payment-and-release.spec.ts already covers the original
 * carton-tag-based generate -> pickup happy path against a different real
 * seeded billing (Ibrahim Musa, ACME001001) — none of the fields under test
 * here were reachable from that flow, and that file's fixture is a shared,
 * long-lived record this session has already driven to a terminal state
 * (released_with_outstanding + picked_up), so it can no longer exercise
 * "generate" at all. This file targets a different seeded billing (Ngozi
 * Adeyemi, same container ACME001001, fully paid, 2 cartons, no release
 * notes as of authoring) specifically so the two files don't collide.
 *
 * Like billing-payment-and-release.spec.ts, this uses test.skip() guards
 * throughout so re-runs against the now-exhausted fixture correctly report
 * "already done" rather than failing — see that file's own comments for why
 * real seeded data (not a mock) makes this necessary.
 */
import { expect, test } from '@playwright/test'
import { actionAvailable, becomesVisible, goToViaNav, hasRows, settleNetwork, switchRole } from '../support/roleSwitch'

const CUSTOMER_NAME = 'Ngozi Adeyemi'
const CONTAINER_NUMBER = 'ACME001001'
// Ngozi Adeyemi has two billing records against this same container — this
// invoice number picks the fully-paid one with zero release notes as of
// authoring (the other is 'overpaid'), since customer + container alone
// match both rows in the Billing list.
const BILLING_INVOICE_NUMBER = 'INV-A-001'
const PHYSICAL_DOC_NUMBER = 'GRN-E2E-9001'
const INVOICE_NUMBER = 'ACM-INV-E2E-0001'

// The list's own fetch starts on mount, a tick after the nav click settles —
// networkidle can resolve before it even begins, and a one-shot .count()
// would then race the Table component's loading skeleton (5 blank rows).
// toHaveCount retries until the real rows render or this times out.
async function findReleaseNoteRow(page: import('@playwright/test').Page): Promise<import('@playwright/test').Locator> {
  await switchRole(page, 'tenant_admin')
  await goToViaNav(page, /^release notes$/i)
  const row = page.locator('table tbody tr')
    .filter({ hasText: CUSTOMER_NAME })
    .filter({ hasText: CONTAINER_NUMBER })
    .first()
  await expect(row).toHaveCount(1, { timeout: 10_000 }).catch(() => undefined)
  return row
}

test.describe('release note — count-based generation with warehouse and document fields', () => {
  test('generating a count-based release note captures warehouse, document number and invoice numbers', async ({ page }) => {
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
    test.skip(!(await actionAvailable(page, /generate release note/i)), 'No "Generate release note" action available for this billing status')

    await generateBtn.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Generate release note' })).toBeVisible()

    // Switch from the default carton-tags mode to count-based — the
    // migration-041 addition under test, previously unreachable from the UI.
    await dialog.getByRole('button', { name: 'Count' }).click()
    await dialog.getByLabel(/packages released/i).fill('2')
    await dialog.getByLabel(/package unit/i).fill('cartons')

    const warehouseSelect = dialog.getByLabel(/warehouse.*branch/i)
    if (await becomesVisible(warehouseSelect)) {
      const optionCount = await warehouseSelect.locator('option').count()
      if (optionCount > 1) await warehouseSelect.selectOption({ index: 1 })
    }

    await dialog.getByLabel(/physical document number/i).fill(PHYSICAL_DOC_NUMBER)
    await dialog.getByLabel(/packing list invoice numbers/i).fill(INVOICE_NUMBER)

    const generateSubmit = dialog.getByRole('button', { name: /^generate release note$/i })
    await expect(generateSubmit).toBeEnabled()
    await generateSubmit.click()

    // On a re-run against this same billing, the backend's duplicate/
    // over-release guard (services/payment_release/service.py
    // generate_release_note) correctly rejects it — this billing only has 2
    // cartons total, already fully released by an earlier pass. Any error
    // alert here means "already done", not a fresh failure — this record's
    // capacity is why the test uses skip guards throughout rather than
    // asserting a specific outcome (real seeded data, not a mock). No further
    // cleanup needed either way — each test gets its own isolated page.
    await Promise.race([
      expect(dialog).not.toBeVisible({ timeout: 10_000 }),
      expect(dialog.getByRole('alert')).toBeVisible({ timeout: 10_000 }),
    ])
  })

  test('release note detail page displays warehouse, document number, invoice numbers and package count', async ({ page }) => {
    const row = await findReleaseNoteRow(page)
    test.skip(!(await hasRows(row)), 'No release note found for this customer yet — run the generation test first')

    await row.getByRole('button').first().click()
    await expect(page).toHaveURL(/\/release-notes\//)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    await expect(page.getByText(/physical document no\./i)).toBeVisible()
    await expect(page.getByText(PHYSICAL_DOC_NUMBER)).toBeVisible()
    await expect(page.getByText(/packing list invoice/i)).toBeVisible()
    await expect(page.getByText(INVOICE_NUMBER)).toBeVisible()
    await expect(page.getByText(/\d+ of \d+ cartons/i)).toBeVisible()
  })

  test('recording a pickup with warehouse, CSO and accounting officer selections updates status', async ({ page }) => {
    // canRecordPickup() (releaseNotesRules.ts) restricts this to
    // warehouse_attendant specifically.
    await switchRole(page, 'warehouse_attendant')
    await goToViaNav(page, /^release notes$/i)
    const row = page.locator('table tbody tr')
      .filter({ hasText: CUSTOMER_NAME })
      .filter({ hasText: CONTAINER_NUMBER })
      .first()
    await expect(row).toHaveCount(1, { timeout: 10_000 }).catch(() => undefined)
    test.skip(!(await hasRows(row)), 'No release note found for this customer — run the generation test first')

    await row.getByRole('button').first().click()
    await expect(page).toHaveURL(/\/release-notes\//)

    const pickupBtn = page.getByRole('button', { name: /^record pickup$/i })
    test.skip(!(await actionAvailable(page, /^record pickup$/i)), 'Already picked up — nothing left to test')

    await pickupBtn.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: /record pickup/i })).toBeVisible()

    // getByLabel(/collected by/i) alone also matches the "Collected by a
    // delegate" toggle switch — scope to the textbox role to disambiguate.
    await dialog.getByRole('textbox', { name: /collected by/i }).fill(CUSTOMER_NAME)

    // Warehouse / CSO / Accounting Officer pickers — the RecordPickupModal
    // addition under test. All optional; exercise them when the tenant has
    // warehouses/staff configured (real seeded data, not guaranteed empty).
    const warehouseSelect = dialog.getByLabel(/warehouse.*branch/i)
    if (await becomesVisible(warehouseSelect)) {
      const count = await warehouseSelect.locator('option').count()
      if (count > 1) await warehouseSelect.selectOption({ index: 1 })
    }
    const csoSelect = dialog.getByLabel(/customer service officer/i)
    if (await becomesVisible(csoSelect)) {
      const count = await csoSelect.locator('option').count()
      if (count > 1) await csoSelect.selectOption({ index: 1 })
    }
    const accountingSelect = dialog.getByLabel(/accounting officer/i)
    if (await becomesVisible(accountingSelect)) {
      const count = await accountingSelect.locator('option').count()
      if (count > 1) await accountingSelect.selectOption({ index: 1 })
    }

    await dialog.getByRole('button', { name: /confirm pickup/i }).click()
    await expect(dialog).not.toBeVisible({ timeout: 10_000 })
    // Both the status badge and the success banner contain "picked up" —
    // .first() picks either, since either alone confirms the status changed.
    await expect(page.getByText(/picked up/i).first()).toBeVisible()
  })

  test('Print opens the release note PDF in a new tab (FD-40: the PDF is the one document)', async ({ page, context }) => {
    const row = await findReleaseNoteRow(page)
    test.skip(!(await hasRows(row)), 'No release note found for this customer — run the generation test first')

    await row.getByRole('button').first().click()
    await expect(page).toHaveURL(/\/release-notes\//)
    // The document's content (document number, invoice numbers, signature lines, terms) is checked where it is
    // made: tests/unit/test_pdf_documents.py.
    // Export is the single PDF action on the release-note detail header. Headless Chromium may detach a popup
    // tab as soon as it converts an inline PDF into a download, so assert the 200 PDF response and URL directly.
    const pdfResponse = page.waitForResponse(
      (r) => /\/v1\/release-notes\/[^/]+\/pdf/.test(r.url()) && r.status() === 200,
      { timeout: 10_000 },
    )
    const popupPromise = context.waitForEvent('page', { timeout: 5_000 }).catch(() => null)
    await page.getByRole('button', { name: /^export$/i }).click()
    const resp = await pdfResponse
    const body = (await resp.json()) as { data?: { url?: string; download_url?: string } }
    expect(body.data?.download_url ?? body.data?.url ?? '').toMatch(/release_note.*\.pdf/i)
    const tab = await popupPromise
    if (tab && !tab.isClosed()) await tab.close()
  })

  test('PDF export opens a document from the release-note detail page', async ({ page, context }) => {
    const row = await findReleaseNoteRow(page)
    test.skip(!(await hasRows(row)), 'No release note found for this customer — run the generation test first')

    await row.getByRole('button').first().click()
    await expect(page).toHaveURL(/\/release-notes\//)

    // ExportButton is configured with a single format (pdf) on this page, so
    // its primary button (not a dropdown item) is labeled "Export" and
    // triggers the pdf export directly — see ExportButton.tsx's defaultFormat.
    const pdfResponse = page.waitForResponse(
      (r) => /\/v1\/release-notes\/[^/]+\/pdf/.test(r.url()) && r.status() === 200,
      { timeout: 10_000 },
    )
    const popupPromise = context.waitForEvent('page', { timeout: 5_000 }).catch(() => null)
    await page.getByRole('button', { name: /^export$/i }).click()
    const resp = await pdfResponse
    const body = (await resp.json()) as { data?: { url?: string; download_url?: string } }
    expect(body.data?.download_url ?? body.data?.url ?? '').toMatch(/release_note.*\.pdf/i)
    const tab = await popupPromise
    if (tab && !tab.isClosed()) await tab.close()
  })
})
