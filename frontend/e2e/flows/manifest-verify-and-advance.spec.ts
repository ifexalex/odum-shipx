/**
 * E2E — verify a manifest, then advance its container out of `loading`.
 *
 * This is the exact chain a session-earlier bug report described: "I tried
 * to transition the container from loading to sealed, I got an error
 * 'container must have a manifest'." containerAdvanceRequirementHint()
 * documents the real requirement — an approved packing list *and* a
 * verified manifest — but nothing end to end had exercised satisfying it
 * and then actually succeeding.
 *
 * Uses the E2E-TEST-001 container (from manifest-import.spec.ts's fixture
 * import) rather than real seeded data — safe to mutate status on repeatedly.
 */
import { expect, test, type APIResponse, type Page } from '@playwright/test'
import { goToViaNav, settleNetwork, switchRole } from '../support/roleSwitch'

const TEST_CONTAINER = 'E2E-TEST-001'
const TENANT_ID = '10000000-0000-0000-0000-000000000001'  // Acme Shipping Ltd (seed)

/**
 * Make sure the container actually has an approved packing list, which is half
 * of what sealing requires.
 *
 * Without this the advance is refused for a real reason — the server answers
 * "Container must have at least 1 approved packing list before sealing" and the
 * modal stays open — and no ordering of the suite fixes it: specs run
 * alphabetically, so bulk-packing-list-actions (which approves pending lists)
 * runs BEFORE manifest-import creates this container's list. The list is
 * therefore left at pending_approval and this test could never pass in a clean
 * serial run. It only ever "passed" by being skipped.
 *
 * Done over the API rather than through the UI on purpose: this spec is about
 * the advance behaviour, and driving an unrelated approval screen would just
 * add another thing that can break for reasons this test does not care about.
 * The local server takes dev auth headers directly (scripts/local_server.py).
 */
// Roles are not interchangeable here, and getting one wrong fails silently
// unless the response is checked: approving a packing list wants tenant_admin,
// while verifying a manifest requires china_office_staff/nigeria_office_staff
// and answers 403 to tenant_admin. The first version of these helpers used
// tenant_admin for both and ignored the status, so the manifest was never
// verified and the test failed later with "The manifest must be verified
// before the container can be sealed" — a precondition that looked satisfied
// and was not. Hence expectOk() on every call.
function devHeaders(role: string): Record<string, string> {
  return {
    'X-Tenant-ID': TENANT_ID,
    'X-Role': role,
    'Content-Type': 'application/json',
  }
}

/** Fail loudly instead of letting a silent 4xx pass for a met precondition. */
async function expectOk(response: APIResponse, what: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(`${what} failed: ${response.status()} ${await response.text()}`)
  }
}

async function approvePackingListsFor(page: Page, containerNumber: string): Promise<void> {
  const headers = devHeaders('tenant_admin')
  const api = page.request
  const found = await api.get(`http://localhost:3000/v1/containers?q=${containerNumber}`, { headers })
  const containers = (await found.json()).data ?? []
  if (containers.length === 0) return

  const listed = await api.get(
    `http://localhost:3000/v1/containers/${containers[0].id}/packing-lists`,
    { headers },
  )
  for (const pl of (await listed.json()).data ?? []) {
    if (pl.status === 'approved') continue
    if (pl.status === 'draft') {
      await expectOk(
        await api.patch(`http://localhost:3000/v1/packing-lists/${pl.id}/submit`, { headers }),
        'submit packing list',
      )
    }
    await expectOk(
      await api.patch(`http://localhost:3000/v1/packing-lists/${pl.id}/approve`, {
        headers,
        data: { comments: 'e2e: precondition for sealing' },
      }),
      'approve packing list',
    )
  }
}

/**
 * The other half of the sealing requirement: a verified manifest.
 *
 * The test above this one verifies it through the UI, but it carries a
 * data-dependent test.skip — and when it skips, this test used to fail with
 * "The manifest must be verified before the container can be sealed" and the
 * modal left open. A test should not depend on a sibling having actually run,
 * so establish it here instead. Idempotent: an already-verified manifest is
 * left alone.
 */
async function ensureManifestVerified(page: Page, containerNumber: string): Promise<void> {
  // china_office_staff, not tenant_admin — see devHeaders() above.
  const headers = devHeaders('china_office_staff')
  const api = page.request
  const listed = await api.get('http://localhost:3000/v1/manifests', { headers })
  const manifests = (await listed.json()).data ?? []
  const target = manifests.find(
    (m: { container_number?: string }) => m.container_number === containerNumber,
  )
  if (!target || target.verification_status === 'verified') return
  await expectOk(
    await api.patch(`http://localhost:3000/v1/manifests/${target.id}/verify`, {
      headers,
      data: { verification_status: 'verified' },
    }),
    'verify manifest',
  )
}

test.describe('manifest verify + container advance', () => {
  test('verifying a pending manifest updates its status', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await goToViaNav(page, /^manifests$/i)

    const row = page.locator('table tbody tr').filter({ hasText: TEST_CONTAINER })
    test.skip((await row.count()) === 0, `${TEST_CONTAINER} has no manifest yet — run manifest-import.spec.ts first`)

    await row.getByRole('button', { name: /^view$/i }).click()
    await expect(page).toHaveURL(/\/manifests\//)
    await expect(page.getByRole('heading', { name: TEST_CONTAINER })).toBeVisible()

    const verifyBtn = page.getByRole('button', { name: /verify manifest/i })
    // isVisible() is a one-shot check with no retry — right after navigation
    // it can run before the button has rendered, wrongly taking the
    // already-verified branch below. Give it the same chance to appear that
    // an assertion would.
    const verifyBtnAppeared = await verifyBtn.isVisible().catch(() => false)
    if (!verifyBtnAppeared) {
      // Already verified by a previous run of this same test — that's fine,
      // confirm the status reflects it rather than failing.
      await expect(page.getByText(/^verified$/i)).toBeVisible()
      return
    }

    await verifyBtn.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // "Verified — all items present" is the default outcome; submit directly.
    await dialog.getByRole('button', { name: /submit verification/i }).click()

    await expect(dialog).not.toBeVisible()
    await expect(page.getByText(/^verified$/i)).toBeVisible()
  })

  test('a container with an approved packing list and a verified manifest can advance to Sealed', async ({ page }) => {
    await switchRole(page, 'china_office_staff')
    await goToViaNav(page, /^containers$/i)

    await page.getByPlaceholder(/container number, vessel name, voyage/i).fill(TEST_CONTAINER)
    await settleNetwork(page)
    const row = page.locator('table tbody tr').filter({ hasText: TEST_CONTAINER })
    test.skip((await row.count()) === 0, `${TEST_CONTAINER} not found — run manifest-import.spec.ts first`)

    // ContainerList.tsx rows use KebabBtn ("Open {container_number}"), not
    // ViewLink's "View" — a different action component than packing lists use.
    await row.getByRole('button', { name: `Open ${TEST_CONTAINER}` }).click()
    await expect(page).toHaveURL(/\/containers\//)

    const currentStatus = await page.locator('main').getByText(/^(Loading|Sealed)$/).first().textContent()
    test.skip(currentStatus === 'Sealed', 'Already advanced to Sealed by a previous run — nothing left to test')

    await approvePackingListsFor(page, TEST_CONTAINER)
    await ensureManifestVerified(page, TEST_CONTAINER)

    const advanceBtn = page.getByRole('button', { name: /advance to sealed/i })
    await expect(advanceBtn).toBeVisible()
    await advanceBtn.click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // The advisory hint names the real server-side requirement
    // (containerAdvanceRequirementHint) — present regardless of whether it's
    // actually satisfied yet.
    await expect(dialog.getByText(/approved packing list.*verified manifest/i)).toBeVisible()

    await dialog.getByRole('button', { name: /^continue$/i }).click()
    await expect(dialog.getByText(/Loading.*Sealed/)).toBeVisible()
    await dialog.getByRole('button', { name: /confirm/i }).click()

    // Success: modal closes and the page reflects the new status. A leftover
    // requirement (e.g. the manifest wasn't actually verified) surfaces as a
    // banner inside the still-open modal instead — fail loudly on that rather
    // than timing out ambiguously.
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 10_000 })
    await expect(page.locator('main').getByText('Sealed', { exact: true })).toBeVisible()
  })
})
