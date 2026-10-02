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

test.describe('dev role survives a reload', () => {
  // Ground-truth bug report: "when i am on tab e.g customer or any other tab
  // and i refresh, it goes to the dashboard." RoleSwitcher's active identity
  // used to live only in React state (LocalAuthProvider) with nothing
  // persisting it, and App.tsx never passes an `initialRole`, so any reload
  // silently reset it to the 'platform_admin' default — RoleGuard then saw
  // the current page's `allow` list no longer matched and bounced to
  // platform_admin's home ("the dashboard"). Fixed via a sessionStorage-
  // backed identity in src/lib/localDevSession.ts. One page per role family
  // (staff/admin, config sub-nav, china office, customer portal) — this bug
  // was systemic across every page, not specific to one.

  test('tenant_admin stays on a sub-page of /admin after a reload', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    await page.goto('/admin/customers')
    await expect(page).toHaveURL(/\/admin\/customers/)

    await page.reload()

    await expect(page).toHaveURL(/\/admin\/customers/)
  })

  test('tenant_admin stays on a Config sub-nav page after a reload', async ({ page }) => {
    await switchRole(page, 'tenant_admin')
    await page.goto('/admin/config/dollar-rate')
    await expect(page).toHaveURL(/\/admin\/config\/dollar-rate/)

    await page.reload()

    await expect(page).toHaveURL(/\/admin\/config\/dollar-rate/)
  })

  test('china_office_staff stays on /packing-lists after a reload', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await page.goto('/packing-lists')
    await expect(page).toHaveURL(/\/packing-lists/)

    await page.reload()

    await expect(page).toHaveURL(/\/packing-lists/)
  })

  test('customer stays on /my-billing after a reload', async ({ page }) => {
    await switchRole(page, 'customer')
    await page.goto('/my-billing')
    await expect(page).toHaveURL(/\/my-billing/)

    await page.reload()

    await expect(page).toHaveURL(/\/my-billing/)
  })
})
