/**
 * Live-browser regression coverage for the app-wide responsive pass
 * (2026-09-20). jsdom (Vitest's unit-test environment) never evaluates
 * `@container`/`@media` queries and has no real layout engine, so these
 * checks can only be done against an actual rendered page — they are the
 * only signal that would have caught the overflow bugs fixed in this pass
 * (fixed-column stat grids, hand-rolled fixed-width modals, hero/toolbar
 * rows without flex-wrap).
 */
import { expect, type Page, test } from '@playwright/test'
import { switchRole } from '../support/roleSwitch'

test.use({ viewport: { width: 375, height: 800 } })

async function assertNoHorizontalOverflow(page: Page, label: string): Promise<void> {
  const overflowing = await page.evaluate(() => {
    const results: { tag: string; cls: string; width: number }[] = []
    document.querySelectorAll('*').forEach((el) => {
      if (el.scrollWidth > document.documentElement.clientWidth + 1) {
        results.push({ tag: el.tagName, cls: (el as HTMLElement).className?.toString().slice(0, 60), width: el.scrollWidth })
      }
    })
    return results.slice(0, 10)
  })
  if (overflowing.length > 0) {
    console.log(`OVERFLOWING ELEMENTS (${label}):`, JSON.stringify(overflowing, null, 2))
  }
  const hasHScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  )
  expect(hasHScroll, `${label}: unexpected horizontal overflow at 375px`).toBe(false)
}

test('BillingList renders card view at phone width, no horizontal overflow', async ({ page }) => {
  await switchRole(page, 'tenant_admin')
  await page.goto('/billing')
  await page.waitForLoadState('networkidle')
  await expect(page.locator('table')).toHaveCount(0)
  await assertNoHorizontalOverflow(page, 'BillingList')
})

test('BillingDetail hero actions (multiple buttons) do not overflow at phone width', async ({ page }) => {
  await switchRole(page, 'tenant_admin')
  await page.goto('/billing')
  await page.waitForLoadState('networkidle')
  const firstCard = page.locator('[class*="card"]').first()
  test.skip((await firstCard.count()) === 0, 'No billing records seeded')
  await firstCard.click()
  await page.waitForLoadState('networkidle')
  await assertNoHorizontalOverflow(page, 'BillingDetail')
})

test('PackingListList bulk-selection bar does not overflow at phone width', async ({ page }) => {
  await switchRole(page, 'tenant_admin')
  await page.goto('/packing-lists')
  await page.waitForLoadState('networkidle')

  // Card view at 375px has no header checkbox row — select via the
  // per-card checkbox instead so the bulk bar actually renders.
  const cardCheckbox = page.getByRole('checkbox').first()
  test.skip((await cardCheckbox.count()) === 0, 'No packing lists seeded')
  await cardCheckbox.click()

  const bulkBar = page.getByText(/packing list\(s\) selected/i)
  await expect(bulkBar).toBeVisible()
  await assertNoHorizontalOverflow(page, 'PackingListList (bulk bar active)')
})

test('customer Account page (all tabs) does not overflow at phone width', async ({ page }) => {
  await switchRole(page, 'customer')
  await page.goto('/account')
  await page.waitForLoadState('networkidle')
  await assertNoHorizontalOverflow(page, 'Account — Profile tab')

  for (const tabName of [/notifications/i, /privacy/i]) {
    const tab = page.getByRole('tab', { name: tabName })
    if (await tab.isVisible().catch(() => false)) {
      await tab.click()
      await assertNoHorizontalOverflow(page, `Account — ${tabName}`)
    }
  }
})

test('customer-portal hamburger drawer opens, navigates, and closes at phone width', async ({ page }) => {
  await switchRole(page, 'customer')
  await page.goto('/my-shipments')
  await page.waitForLoadState('networkidle')

  const hamburger = page.getByRole('button', { name: /open menu/i })
  await expect(hamburger).toBeVisible()
  await hamburger.click()

  const drawerAccountLink = page.getByRole('button', { name: /account/i }).last()
  await expect(drawerAccountLink).toBeVisible()
  await drawerAccountLink.click()

  await expect(page).toHaveURL(/\/account/)
  await expect(page.getByRole('button', { name: /open menu/i })).toBeVisible()
})
