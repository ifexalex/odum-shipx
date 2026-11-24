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
 *
 * Both tests establish their own preconditions over the API. That principle was
 * applied to the second test when it was written and NOT to the first, which is
 * why the first skipped on every clean run for as long as it existed: it needed
 * an approved packing list (the only thing that creates a manifest) and waited
 * for one nobody had approved.
 */
import { expect, test, type APIResponse, type Page } from '@playwright/test'
import { actionAvailable, goToViaNav, hasRows, settleNetwork, switchRole } from '../support/roleSwitch'

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

    // Establish this test's OWN precondition, rather than inheriting one.
    //
    // A `manifest` row is created in exactly one place: the packing-list
    // approval side-effects (`_apply_approval_side_effects`, which is the only
    // caller of `create_manifest`). Importing a forwarder manifest does NOT
    // create one — it creates the container and a packing list, and the
    // manifest appears only once that list is approved.
    //
    // So this test skipped on every clean serial run, and its message
    // ("run manifest-import.spec.ts first") pointed at the wrong fixture:
    // manifest-import HAD run, immediately before, and passed. Proved from a
    // Playwright trace — GET /v1/manifests returned 200 with two rows, neither
    // of them this container, and the row was written 11.9s LATER by the next
    // test in this same file, which approves the packing list as its own setup.
    //
    // It also explains a misleading pass: run this file alone after a previous
    // full run and it passes, because that run's second test left a manifest
    // behind. Isolation was testing leftover state, not the fixture.
    await approvePackingListsFor(page, TEST_CONTAINER)

    await goToViaNav(page, /^manifests$/i)

    const row = page.locator('table tbody tr').filter({ hasText: TEST_CONTAINER })
    // Now a skip means the CONTAINER is missing — manifest-import really did
    // not run — which is the only remaining honest reason to skip.
    test.skip(!(await hasRows(row)), `${TEST_CONTAINER} not found — run manifest-import.spec.ts first`)

    await row.getByRole('button').first().click()
    await expect(page).toHaveURL(/\/manifests\//)
    await expect(page.getByRole('heading', { name: TEST_CONTAINER })).toBeVisible()

    const verifyBtn = page.getByRole('button', { name: /verify manifest/i })
    // This comment used to correctly describe the problem — "isVisible() is a
    // one-shot check with no retry ... give it the same chance to appear that an
    // assertion would" — and then call isVisible() anyway. The right diagnosis
    // with the wrong code, so the bug it warned about was live: run before the
    // button rendered and the test silently takes the already-verified branch
    // and never exercises verification at all.
    const verifyBtnAppeared = await actionAvailable(page, /verify manifest/i)
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
    test.skip(!(await hasRows(row)), `${TEST_CONTAINER} not found — run manifest-import.spec.ts first`)

    // ContainerList.tsx rows use Table's first-cell openButton ("Open container {container_number}").
    await row.getByRole('button', { name: new RegExp(`open.*${TEST_CONTAINER}`, 'i') }).click()
    await expect(page).toHaveURL(/\/containers\//)

    const currentStatus = await page.locator('main').getByText(/^(Loading|Sealed)$/).first().textContent()
    test.skip(currentStatus === 'Sealed', 'Already advanced to Sealed by a previous run — nothing left to test')

    await approvePackingListsFor(page, TEST_CONTAINER)
    await ensureManifestVerified(page, TEST_CONTAINER)

    const advanceBtn = page.getByRole('button', { name: /seal container|advance to sealed/i })
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
    await expect(page.locator('main').getByText('Sealed', { exact: true }).first()).toBeVisible()
  })
})
