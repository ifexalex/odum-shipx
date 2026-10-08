/**
 * E2E — customer account-creation invite claim (public, no login).
 *
 * From 12_testing_strategy.md's customer-account-creation flow: a customer
 * created without a login (typically by manifest import) gets an expiring,
 * single-use link to /invite/:token. This exercises the real claim flow
 * against the local Flask server — token minted directly via
 * scripts/mint_test_invite.py, since the real API never returns a raw token
 * (see e2e/support/mintInvite.ts for why).
 */
import { expect, test } from '@playwright/test'
import { mintTestInvite } from '../support/mintInvite'

// A strong password meeting every rule InviteClaimScreen checks, so tests
// aren't tied to guessing which rule the UI enforces.
const STRONG_PASSWORD = 'Correct-Horse-9-Battery!'

test.describe('customer invite claim', () => {
  test('valid invite: shows customer name and creates the account', async ({ page }) => {
    const { token } = mintTestInvite()

    await page.goto(`/invite/${token}`)
    await expect(page.getByText(/create your account|welcome/i)).toBeVisible()

    const email = `e2e-${Date.now()}@example.com`
    await page.getByLabel(/email address/i).fill(email)
    await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
    await page.getByLabel(/confirm password/i).fill(STRONG_PASSWORD)

    await page.getByRole('button', { name: /create account/i }).click()

    await expect(page.getByText('Account created.')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(email)).toBeVisible()
  })

  test('mismatched passwords block submission', async ({ page }) => {
    const { token } = mintTestInvite()
    await page.goto(`/invite/${token}`)
    await expect(page.getByText(/create your account|welcome/i)).toBeVisible()

    await page.getByLabel(/email address/i).fill(`e2e-${Date.now()}@example.com`)
    await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
    await page.getByLabel(/confirm password/i).fill(STRONG_PASSWORD + 'x')

    await expect(page.getByText("Passwords don't match.")).toBeVisible()
    await expect(page.getByRole('button', { name: /create account/i })).toBeDisabled()
  })

  test('an already-consumed invite shows the "no longer valid" state, not a raw error', async ({ page }) => {
    const { token } = mintTestInvite()

    // Consume it once via a fresh context (claiming doesn't require staying
    // on the same page — this simulates "already used").
    await page.goto(`/invite/${token}`)
    const email = `e2e-${Date.now()}@example.com`
    await page.getByLabel(/email address/i).fill(email)
    await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
    await page.getByLabel(/confirm password/i).fill(STRONG_PASSWORD)
    await page.getByRole('button', { name: /create account/i }).click()
    await expect(page.getByText('Account created.')).toBeVisible({ timeout: 10_000 })

    // Re-visit the same link — the token is now consumed.
    await page.goto(`/invite/${token}`)
    await expect(page.getByText('This link is no longer valid.')).toBeVisible()
    await expect(page.getByRole('button', { name: /back to sign in/i })).toBeVisible()
  })

  test('an unknown token shows the same friendly invalid state', async ({ page }) => {
    await page.goto('/invite/this-token-was-never-issued')
    await expect(page.getByText('This link is no longer valid.')).toBeVisible()
  })
})
