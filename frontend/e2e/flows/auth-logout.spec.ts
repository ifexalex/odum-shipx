/**
 * E2E — real Cognito login/logout must actually end the session, reload included.
 *
 * Ground-truth bug report: "i logged in as ifesinachi (customer), when i
 * logout and refresh the page it still logged in." Root cause was
 * LocalAuthProvider always falling back to its dev-identity shim session the
 * instant the real Cognito session cleared — including across a reload,
 * since that fallback is keyed off `identity` state, not the logout action.
 * See src/auth/LocalAuthProvider.tsx and src/lib/localDevSession.ts.
 *
 * Uses a real invite-claimed account (real Cognito login against Moto) rather
 * than the dev role-switcher, since the switcher never exercises this path at
 * all — it's the genuine-login code path this bug lived in.
 */
import { expect, test } from '@playwright/test'
import { mintTestInvite } from '../support/mintInvite'

const STRONG_PASSWORD = 'Correct-Horse-9-Battery!'

async function claimInviteAndLogin(page: import('@playwright/test').Page): Promise<string> {
  const { token } = mintTestInvite()
  const email = `e2e-logout-${Date.now()}@example.com`

  await page.goto(`/invite/${token}`)
  await page.getByLabel(/email address/i).fill(email)
  await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
  await page.getByLabel(/confirm password/i).fill(STRONG_PASSWORD)
  await page.getByRole('button', { name: /create account/i }).click()
  await expect(page.getByText('Account created.')).toBeVisible({ timeout: 10_000 })

  await page.goto('/login')
  await page.getByLabel(/email address/i).fill(email)
  await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/my-shipments/, { timeout: 10_000 })

  return email
}

test.describe('real login/logout session lifecycle', () => {
  test('logging out sends the customer to the login screen, not the dev-identity fallback', async ({ page }) => {
    await claimInviteAndLogin(page)

    await page.getByRole('button', { name: 'Log out' }).click()

    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
    // Not just the URL — the dev shim (always-on when logged out) must not
    // silently render a different, still-authenticated role's home page.
    await expect(page.getByLabel(/email address/i)).toBeVisible()
  })

  test('reloading right after logout stays on the login screen', async ({ page }) => {
    await claimInviteAndLogin(page)
    await page.getByRole('button', { name: 'Log out' }).click()
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })

    await page.reload()

    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })
    await expect(page.getByLabel(/email address/i)).toBeVisible()
  })

  test('navigating to a protected route after logout+reload bounces back to login', async ({ page }) => {
    await claimInviteAndLogin(page)
    await page.getByRole('button', { name: 'Log out' }).click()
    await page.reload()

    await page.goto('/my-shipments')

    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })
  })

  test('logging back in after a logout+reload still works', async ({ page }) => {
    const email = await claimInviteAndLogin(page)
    await page.getByRole('button', { name: 'Log out' }).click()
    await page.reload()
    await expect(page.getByLabel(/email address/i)).toBeVisible()

    await page.getByLabel(/email address/i).fill(email)
    await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
    await page.getByRole('button', { name: /sign in/i }).click()

    await expect(page).toHaveURL(/\/my-shipments/, { timeout: 10_000 })
  })
})
