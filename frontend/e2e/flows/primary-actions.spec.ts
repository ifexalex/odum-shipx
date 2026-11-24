/**
 * E2E — the design step 4 gate (audit brief, "Flows"): each role completes its main flow using only the primary
 * action on each screen — the button in the page header's primary slot (`[data-sticky-action]`), or a form's or
 * dialog's single primary button where the screen is a form. No overflow menus, no secondary row actions.
 *
 *   china_office_staff   create a packing list and submit it for approval (creating the container it needs if none
 *                        is loading, through the wizard's own link)
 *   tenant_admin         approve that packing list
 *   nigeria_office_staff record a payment on an unpaid invoice
 *   warehouse_attendant  scan a release note and record the pickup, keyboard only
 *   customer             pay an invoice (the Paystack hand-off is stubbed: it leaves the app)
 *   platform_admin       onboard a tenant
 *
 * Runs serially against the local stack (make stack), on seeded data, and creates records each run. Every contact it
 * types is an example.com address; nothing reaches a real customer.
 */
import { expect as baseExpect, test, type Page } from '@playwright/test'
import { goToViaNav, settleNetwork, switchRole } from '../support/roleSwitch'

test.describe.configure({ mode: 'serial' })
// The local API serves one request at a time, so a detail page can take several seconds under the suite.
const expect = baseExpect.configure({ timeout: 20_000 })

/** The page header's primary action: the one button the screen leads with. */
function headerPrimary(page: Page) {
  return page.locator('[data-sticky-action]').getByRole('button')
}

/** A valid ISO 6346 container number (owner code, serial, check digit), unique enough per run. */
function containerNumber(): string {
  const owner = 'PRMU'
  const serial = String(Date.now() % 1_000_000).padStart(6, '0')
  const value = (ch: string): number => {
    if (/\d/.test(ch)) return Number(ch)
    // Letters map to 10..38, skipping multiples of 11.
    let n = 10
    for (let c = 'A'.charCodeAt(0); c < ch.charCodeAt(0); c += 1) {
      n += 1
      if (n % 11 === 0) n += 1
    }
    return n
  }
  const sum = [...(owner + serial)].reduce((acc, ch, i) => acc + value(ch) * 2 ** i, 0)
  return `${owner}${serial}${(sum % 11) % 10}`
}

let submittedPath: string | null = null

test('china office: a packing list goes from nothing to awaiting approval', async ({ page }) => {
  await switchRole(page, 'china_office_staff')
  await goToViaNav(page, /packing lists/i)
  await headerPrimary(page).click()
  await expect(page).toHaveURL(/\/packing-lists\/new/)

  // No container loading: the wizard names it and links to creating one, which comes back here (FD-25).
  const createContainer = page.getByRole('link', { name: 'Create a container' })
  const containerPicker = page.getByRole('button', { name: 'Container', exact: true })
  await expect(createContainer.or(containerPicker.and(page.locator(':enabled')))).toBeVisible()
  if (await createContainer.isVisible()) {
    await createContainer.click()
    await page.getByLabel(/Container number/).fill(containerNumber())
    await page.getByRole('button', { name: 'Create container' }).click()
    await expect(page).toHaveURL(/\/packing-lists\/new/)
  }

  await page.getByRole('button', { name: 'Customer', exact: true }).click()
  await page.getByRole('option').first().click()
  await expect(containerPicker).toBeEnabled()
  await containerPicker.click()
  await page.getByRole('option').first().click()
  await page.getByRole('button', { name: 'Next: Add items' }).click()
  await page.getByLabel('Description, item 1').fill('E2E primary-action cartons')
  await page.getByRole('button', { name: 'Next: Review' }).click()
  await page.getByRole('button', { name: 'Submit for approval' }).click()

  await expect(page).toHaveURL(/\/packing-lists\/[0-9a-f-]{36}$/)
  await expect(page.getByText('Pending approval').first()).toBeVisible()
  submittedPath = new URL(page.url()).pathname
})

test('tenant admin: approves the packing list from its page header', async ({ page }) => {
  test.skip(!submittedPath, 'needs the packing list the China office test submitted')
  await switchRole(page, 'tenant_admin')
  // The dev identity survives a reload (LocalAuthProvider keeps it in the tab), so the list opens by its address.
  await page.goto(submittedPath!)
  await expect(headerPrimary(page)).toHaveText(/Approve/)
  await headerPrimary(page).click()
  await expect(page.getByText('Packing list approved')).toBeVisible()
  await expect(page.getByText('Approved').first()).toBeVisible()
})

test('nigeria office: records a payment on an unpaid invoice from its page header', async ({ page }) => {
  await switchRole(page, 'nigeria_office_staff')
  await goToViaNav(page, /^billing$/i)
  const row = page.locator('table tbody tr').filter({ has: page.getByRole('button', { name: 'Record payment' }) }).first()
  test.skip(!(await row.isVisible().catch(() => false)), 'no unpaid invoice in the seed data')
  await row.getByRole('button', { name: 'Record payment' }).click()
  await expect(page).toHaveURL(/\/billing\//)
  await expect(headerPrimary(page)).toHaveText(/Record payment/)
  await headerPrimary(page).click()
  await page.getByLabel(/Amount/).fill('1000')
  await page.getByRole('button', { name: 'Confirm payment' }).click()
  await expect(page.getByText('Payment recorded')).toBeVisible()
})

test('warehouse: scans a release note and records the pickup with the keyboard only', async ({ page }) => {
  await switchRole(page, 'warehouse_attendant')
  // The queue's count shows once the active list has loaded.
  await expect(page.getByText(/^\d+ notes?$/)).toBeVisible()
  const reference = page.locator('[class*="cardRef"]').first()
  test.skip((await reference.count()) === 0, 'no active release note to collect')
  const ref = (await reference.innerText()).trim()
  // The field has focus on arrival (FD-26): a scanner types and sends Enter.
  await expect(page.getByLabel('Release note reference')).toBeFocused()
  await page.keyboard.type(`${ref}\n`)
  const sheet = page.getByRole('dialog')
  await expect(sheet.getByRole('button', { name: 'Confirm pickup' })).toBeVisible()
  test.skip(await sheet.getByText('Pickup code locked').isVisible(), 'the note is locked')
  test.skip(await sheet.getByLabel(/Pickup code/).isVisible().catch(() => false), 'the note needs a code sent to the customer')
  await page.keyboard.press('Enter')
  await expect(page.getByText('Pickup recorded')).toBeVisible()
  await expect(page.getByLabel('Release note reference')).toBeFocused()
})

test('customer: pays an invoice from its page header', async ({ page }) => {
  await switchRole(page, 'customer')
  await goToViaNav(page, /billing/i)
  // Invoices are cards; one with an amount owed says so.
  const cards = page.locator('[role="button"][tabindex="0"]').filter({ hasText: 'Total due' })
  await expect(cards.first().or(page.getByText('No billing records yet.'))).toBeVisible()
  const owing = cards.filter({ hasText: /outstanding/ }).first()
  test.skip((await owing.count()) === 0, 'no invoice with an amount owed')
  await owing.click()
  // Paystack is outside the app: stand in for it, and check the hand-off happens.
  await page.route('**/v1/payments/*/initialize', (route) =>
    route.fulfill({
      json: { data: { authorization_url: `${new URL(page.url()).origin}/paystack-stub`, reference: 'e2e', access_code: 'e2e', amount_ngn: '1' } },
    }),
  )
  await expect(headerPrimary(page)).toHaveText(/^Pay ₦/)
  await headerPrimary(page).click()
  await expect(page).toHaveURL(/\/paystack-stub$/)
})

test('platform admin: onboards a tenant from the tenant list', async ({ page }) => {
  await switchRole(page, 'platform_admin')
  await goToViaNav(page, /^tenants$/i)
  await expect(headerPrimary(page)).toHaveText(/Onboard tenant/)
  await headerPrimary(page).click()
  const stamp = Date.now()
  await page.getByLabel(/Company name/).fill(`E2E Primary ${stamp} Ltd`)
  await page.getByLabel(/Primary contact email/).fill(`ops+${stamp}@example.com`)
  await page.getByLabel(/^Full name/).fill('E2E Admin')
  await page.getByLabel(/^Email/).fill(`admin+${stamp}@example.com`)
  await page.getByRole('button', { name: 'Create tenant' }).click()
  await expect(page.getByText(/is live\./)).toBeVisible()
})
