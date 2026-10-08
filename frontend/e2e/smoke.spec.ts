import { expect, test } from '@playwright/test'

// Smoke: the built artifact boots and the app shell renders. Unauthenticated
// visitors land on the public marketing landing page (RootRedirect → LandingPage).
test('app shell loads and shows the marketing landing page', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Run your entire cargo operation/ })).toBeVisible()
})

// The landing page's "Sign in" link still reaches the real login screen.
test('landing page sign-in link reaches the login screen', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Sign in' }).first().click()
  await expect(page.getByRole('heading', { name: 'Sign in to ShipX' })).toBeVisible()
})
