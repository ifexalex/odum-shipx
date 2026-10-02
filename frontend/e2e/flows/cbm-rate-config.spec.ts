/**
 * E2E — CBM rate config page (currency + flat/per-package-type modes,
 * 2026-09-20). Real backend round-trip, not mocked — this class of bug is
 * specifically invisible to a vitest unit test that mocks the API client:
 * `services/tenant_management/service.py::get_cbm_rate` returns raw
 * Decimal values, and shared/responses.py's success() serializes anything
 * json.dumps doesn't natively recognize via `default=str` — so a Decimal
 * silently became a JSON *string* over the wire, while a mocked unit test
 * (which just returns a JS number literal) never exercises real JSON
 * serialization at all. Reproduced live: loading this page crashed with
 * `config.carton_rate.toFixed is not a function` — caught only by actually
 * loading the real page against the real backend.
 */
import { expect, test } from '@playwright/test'
import { switchRole } from '../support/roleSwitch'

test.describe('CBM rate config', () => {
  test('loads real rates from the backend without crashing, in both modes', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    // First navigation after switchRole — page.goto() is safe here (see
    // e2e/support/roleSwitch.ts's own notes on why it isn't safe later).
    await page.goto('/admin/config/cbm-rate')

    await expect(page.getByText(/per CBM$/)).toBeVisible()

    await page.getByRole('button', { name: 'By package type' }).first().click()
    await expect(page.getByText(/Cartons \([$₦] per CBM\)/)).toBeVisible()
    await expect(page.getByText(/Bags \([$₦] per CBM\)/)).toBeVisible()
    await expect(page.getByText(/Bales \([$₦] per CBM\)/)).toBeVisible()

    await page.getByRole('button', { name: 'Naira (₦)' }).click()
    await expect(page.getByText('Cartons (₦ per CBM)')).toBeVisible()

    await page.getByRole('button', { name: 'Dollar ($)' }).click()
    await expect(page.getByText('Cartons ($ per CBM)')).toBeVisible()
  })

  test('submitting a flat-rate update persists and reflects the new value', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    await page.goto('/admin/config/cbm-rate')
    await expect(page.getByText(/per CBM$/)).toBeVisible()

    await page.getByRole('button', { name: 'Single rate' }).first().click()
    const input = page.getByPlaceholder('e.g. 45')
    await input.fill('52')
    await page.getByRole('button', { name: 'Update rate' }).click()

    await expect(page.getByText('CBM rate updated successfully.')).toBeVisible()
    await expect(page.getByText('$52.00 per CBM')).toBeVisible()

    // Real reload — confirm the persisted value round-trips through a
    // fresh GET, not just the in-memory state right after the PUT response.
    await page.reload()
    await expect(page.getByText('$52.00 per CBM')).toBeVisible()

    // Restore the seeded default so this test doesn't permanently drift
    // shared tenant config for other tests/manual testing.
    await input.fill('45')
    await page.getByRole('button', { name: 'Update rate' }).click()
    await expect(page.getByText('$45.00 per CBM')).toBeVisible()
  })
})
