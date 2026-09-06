/**
 * E2E — authentication and role-appropriate landing pages.
 *
 * Uses the local dev auth shim (LocalAuthProvider + RoleSwitcher) — no real
 * Cognito users required. Requires the local stack to be running (make up).
 */
import { expect, test } from '@playwright/test'
import { switchRole } from '../support/roleSwitch'

test.describe('role-appropriate landing pages', () => {
  test('china_office_staff lands on /containers', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await expect(page).toHaveURL(/\/containers/)
    await expect(page.getByRole('heading', { name: /containers/i })).toBeVisible()
  })

  test('nigeria_office_staff lands on /dashboard', async ({ page }) => {
    await switchRole(page, 'nigeria_office_staff')
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('tenant_admin lands on /dashboard', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('warehouse_attendant lands on /warehouse', async ({ page }) => {
    await switchRole(page, 'warehouse_attendant')
    await expect(page).toHaveURL(/\/warehouse/)
  })

  test('customer lands on /my-shipments', async ({ page }) => {
    await switchRole(page, 'customer')
    await expect(page).toHaveURL(/\/my-shipments/)
  })

  test('platform_admin lands on /platform/dashboard', async ({ page }) => {
    // Expectation must match src/auth/roleHome.ts, the single source of truth
    // for role → landing path (used by both login redirect and RoleGuard).
    await switchRole(page, 'platform_admin')
    await expect(page).toHaveURL(/\/platform\/dashboard/)
  })
})
