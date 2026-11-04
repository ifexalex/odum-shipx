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
import { settleNetwork, switchRole } from '../support/roleSwitch'

test.describe('CBM rate config', () => {
  test('loads real rates from the backend without crashing, in both modes', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    // First navigation after switchRole — page.goto() is safe here (see
    // e2e/support/roleSwitch.ts's own notes on why it isn't safe later).
    await page.goto('/admin/config/cbm-rate')

    await expect(page.getByText(/per CBM$/)).toBeVisible()
    // Let the page's own GETs finish before touching the form.
    //
    // main.tsx wraps the app in <StrictMode>, so in dev React invokes this
    // page's load effect TWICE and a second configApi.getCbmRate() is still in
    // flight after the form renders. When it resolves it re-applies the
    // persisted config — setRateMode/setCurrency/setCartonRate — silently
    // discarding anything selected or typed in the meantime. Against the
    // deliberately single-threaded local API that second response can be
    // seconds late, which is precisely when a test has already clicked.
    //
    // It produced two failures that looked like nothing on screen: "By package
    // type" reverting to "Single rate" (so the Cartons/Bags/Bales labels
    // vanished mid-test), and a typed rate reset to the old value so the save
    // persisted the wrong number. Not a production bug — StrictMode's double
    // invoke is dev-only, and the form is gated on `loading` — but it makes
    // interacting before settling unsound here.
    await settleNetwork(page)

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
    // Same StrictMode double-fetch caveat as the test above.
    await settleNetwork(page)

    // Pin the currency rather than inheriting whatever the last run persisted:
    // the save sends the currently selected currency, so without this the
    // assertions below ("$52.00 per CBM") depend on prior state and fail once
    // another run has left the tenant on naira. This spec mutates shared
    // tenant config, so it has to establish what it asserts on.
    await page.getByRole('button', { name: 'Dollar ($)' }).click()
    await page.getByRole('button', { name: 'Single rate' }).first().click()
    const input = page.getByPlaceholder('e.g. 45')
    await input.fill('52')
    // Guard the fill before submitting. The form seeds itself from the config
    // GET, so a value typed while that is still settling can be overwritten
    // back to the persisted one — and then "Update rate" saves the OLD number
    // and every assertion below fails for a reason nothing on screen explains.
    // Seen exactly that: the input read 45 again and the rate history recorded
    // a +$0 change. Asserting the value first makes the race fail loudly here.
    await expect(input).toHaveValue('52')
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
