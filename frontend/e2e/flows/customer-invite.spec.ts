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
import { expect, test, type Page } from '@playwright/test'
import { mintTestInvite, uniqueTestEmail } from '../support/mintInvite'

// A strong password meeting every rule InviteClaimScreen checks, so tests
// aren't tied to guessing which rule the UI enforces.
const STRONG_PASSWORD = 'Correct-Horse-9-Battery!'

// Every test in here creates a real account against Moto's Cognito, and the
// local API is deliberately single-threaded (scripts/local_server.py runs
// threaded=False — shared/db.py's connection singleton is not thread-safe).
// The 30s default is not enough margin for that when the suite runs the whole
// file set back to back.
test.describe.configure({ timeout: 120_000 })

/**
 * Open an invite link and wait for the claim form to actually be ready.
 *
 * InviteClaimScreen renders "Loading your invite…" until `GET /v1/invites/{token}`
 * resolves, so a bare `goto` + default 5s assertion is a race against that
 * request — not against page rendering. It lost that race deterministically
 * when this spec ran straight after auth-logout.spec.ts: that spec's logout
 * path makes Cognito `RevokeToken` calls which intermittently 500 and are
 * retried four times, and on a single-threaded server this invite fetch simply
 * queues behind them. The failure looked like a missing form; the snapshot
 * showed the page still on "Loading your invite…".
 *
 * So wait on the form explicitly, with room for a queued request. This is a
 * wait for a known-slow dependency, not a blanket timeout bump — the
 * assertions after it keep their normal timeouts.
 */
async function openInviteForm(page: Page, token: string): Promise<void> {
  await page.goto(`/invite/${token}`)
  await expect(page.getByText(/create your account|welcome/i)).toBeVisible({ timeout: 30_000 })
}

test.describe('customer invite claim', () => {
  test('valid invite: shows customer name and creates the account', async ({ page }) => {
    const { token } = mintTestInvite()

    await openInviteForm(page, token)

    const email = uniqueTestEmail()
    await page.getByLabel(/email address/i).fill(email)
    await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
    await page.getByLabel(/confirm password/i).fill(STRONG_PASSWORD)

    await page.getByRole('button', { name: /create account/i }).click()

    await expect(page.getByText('Account created.')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(email)).toBeVisible()
  })

  test('mismatched passwords block submission', async ({ page }) => {
    const { token } = mintTestInvite()
    await openInviteForm(page, token)

    await page.getByLabel(/email address/i).fill(uniqueTestEmail())
    await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
    await page.getByLabel(/confirm password/i).fill(STRONG_PASSWORD + 'x')

    await expect(page.getByText("Passwords don't match.")).toBeVisible()
    await expect(page.getByRole('button', { name: /create account/i })).toBeDisabled()
  })

  test('an already-consumed invite shows the "no longer valid" state, not a raw error', async ({ page }) => {
    const { token } = mintTestInvite()

    // Consume it once via a fresh context (claiming doesn't require staying
    // on the same page — this simulates "already used").
    await openInviteForm(page, token)
    const email = uniqueTestEmail()
    await page.getByLabel(/email address/i).fill(email)
    await page.getByLabel(/^password/i).fill(STRONG_PASSWORD)
    await page.getByLabel(/confirm password/i).fill(STRONG_PASSWORD)
    await page.getByRole('button', { name: /create account/i }).click()
    await expect(page.getByText('Account created.')).toBeVisible({ timeout: 10_000 })

    // Re-visit the same link — the token is now consumed.
    // Same queued-request caveat as openInviteForm(): this state also appears
    // only once GET /v1/invites/{token} has come back.
    await page.goto(`/invite/${token}`)
    await expect(page.getByText('This link is no longer valid.')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('button', { name: /back to sign in/i })).toBeVisible()
  })

  test('an unknown token shows the same friendly invalid state', async ({ page }) => {
    await page.goto('/invite/this-token-was-never-issued')
    await expect(page.getByText('This link is no longer valid.')).toBeVisible({ timeout: 30_000 })
  })
})
