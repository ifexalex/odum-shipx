/**
 * E2E — file a damage claim as a customer, then inspect, resolve (as a
 * refund), and check the resulting refund request through to a decision.
 *
 * Uses the seeded "customer" dev identity (Ngozi Adeyemi) and her real
 * container ACME001002 / carton tags ACME-002-001, ACME-002-002 — no claims
 * or refunds existed in seed data at all, so this is what creates the first
 * ones to test the staff-side workflows against.
 */
import { expect, test } from '@playwright/test'
import { dataRows, goToViaNav, settleNetwork, switchRole } from '../support/roleSwitch'

const CONTAINER_NUMBER = 'ACME001002'
const CARTON_TAGS = 'ACME-002-001, ACME-002-002'

test.describe('claims and refunds', () => {
  test('customer files a damage claim end to end', async ({ page }) => {
    await switchRole(page, 'customer')
    await goToViaNav(page, /^claims$/i)
    await page.getByRole('button', { name: /file a claim|new claim|\+/i }).first().click()

    await expect(page).toHaveURL(/\/my-claims\/new/)

    // Step 1 is a dropdown of the customer's *arrived* shipments, not a
    // free-text container field — MyClaimsNew.tsx was changed to mirror
    // `_PRE_ARRIVAL_STATUSES` server-side (2026-09-06) and this spec still
    // typed into the field that change removed, which is why it timed out.
    const shipmentSelect = page.getByLabel(/which shipment/i)
    await expect(shipmentSelect).toBeVisible()
    const option = shipmentSelect.locator(`option:has-text("${CONTAINER_NUMBER}")`)
    test.skip(
      (await option.count()) === 0,
      `No arrived shipment for container ${CONTAINER_NUMBER} — reseed (make stack)`,
    )
    await shipmentSelect.selectOption({ value: await option.first().getAttribute('value') ?? '' })

    await page.getByLabel(/description of damage/i).fill('e2e test — two cartons arrived with water damage.')
    await page.getByLabel(/carton tags affected/i).fill(CARTON_TAGS)

    await page.getByRole('button', { name: /next: add evidence/i }).click()
    await expect(page.getByText(/step 2 of 3/i)).toBeVisible()

    await page.getByRole('button', { name: /skip.*add later/i }).click()
    await expect(page.getByText(/step 3 of 3/i)).toBeVisible()
    await expect(page.getByText(CONTAINER_NUMBER)).toBeVisible()

    await page.getByRole('button', { name: /done.*view my claims/i }).click()
    await expect(page.getByText('Claim filed!')).toBeVisible()
  })

  test('staff inspects and resolves the claim as a refund above the staff limit', async ({ page }) => {
    // nigeria_office_staff's own limit hint is ₦25,000 (ClaimDetail.tsx's
    // _STAFF_LIMIT_HINT_NGN) — this amount is well above it, to check
    // whether the approval-threshold escalation to tenant_admin is actually
    // enforced server-side, not just shown as a warning banner client-side.
    const REFUND_AMOUNT_NGN = '500000'

    await switchRole(page, 'nigeria_office_staff')
    await goToViaNav(page, /^claims$/i)
    await page.getByPlaceholder(/claim id, customer, container/i).fill('DC-')
    await settleNetwork(page)
    await page.waitForTimeout(300)

    const row = dataRows(page).filter({ hasText: /filed|under inspection|inspection complete|pending resolution/i }).first()
    test.skip((await row.count()) === 0, 'No open claim found — run the filing test first')
    // ClaimList.tsx's row action label depends on status (rowAction()):
    // "Start inspection" / "Complete" / "Resolve" / "View" — not a fixed
    // label, same pattern as BillingList.tsx.
    await row.getByRole('button', { name: /start inspection|complete|resolve|^view$/i }).click()
    await expect(page).toHaveURL(/\/claims\//)
    // Without this, the immediately-following isVisible() check can run while
    // the page still shows "Loading claim…", wrongly concluding no
    // inspection is needed — which is exactly what silently no-op'd this
    // step on every earlier run of this test (every claim stayed 'filed').
    await expect(page.getByText('Claim details')).toBeVisible()

    // Start inspection if still 'filed' — resolve requires under_inspection+.
    const startBtn = page.getByRole('button', { name: /start inspection/i })
    if (await startBtn.isVisible().catch(() => false)) {
      await startBtn.click()
      const inspectDialog = page.getByRole('dialog')
      await expect(inspectDialog).toBeVisible()
      // Default method (delegate_visit) needs no evidence — submit directly.
      await inspectDialog.getByRole('button', { name: /^start inspection$/i }).click()
      await expect(inspectDialog).not.toBeVisible({ timeout: 10_000 })
    }

    await expect(page.getByText('Claim details')).toBeVisible()
    const resolveBtn = page.getByRole('button', { name: /resolve claim/i })
    test.skip(!(await resolveBtn.isVisible().catch(() => false)), 'Claim already resolved by a previous run')
    await resolveBtn.click()

    const resolveDialog = page.getByRole('dialog')
    await expect(resolveDialog.getByRole('heading', { name: 'Resolve claim' })).toBeVisible()
    // ResolutionPick's accessible name concatenates its title and sub-text
    // ("RefundCash refund to customer") — anchor on the start only.
    await resolveDialog.getByRole('button', { name: /^refund/i }).click()
    // The over-threshold warning is computed from the entered amount
    // (likelyNeedsAdminApproval), so it only appears once one is typed.
    await resolveDialog.getByLabel(/amount/i).fill(REFUND_AMOUNT_NGN)
    await expect(resolveDialog.getByText(/exceeds the staff approval limit/i)).toBeVisible()
    await resolveDialog.getByLabel(/reason/i).fill('e2e test — high-value refund as nigeria_office_staff')

    // Fixed ground-truth gap: resolve_claim's threshold check used to read
    // req.amount_usd, a field the real frontend request never populates
    // (ResolveClaimInput only ever sends amount_ngn) — so this ₦500,000
    // refund from nigeria_office_staff used to be silently accepted with no
    // tenant_admin escalation. Fixed by converting amount_ngn via the
    // tenant's dollar rate (services/claims/service.py::resolve_claim).
    // A staff member submitting this now gets a clean rejection, not a
    // silent bypass.
    const submitBtn = resolveDialog.getByRole('button', { name: /^resolve claim$/i })
    await submitBtn.click()

    await expect(resolveDialog.getByText(/action failed/i)).toBeVisible({ timeout: 10_000 })
    await expect(resolveDialog.getByText(/tenant_admin approval required/i)).toBeVisible()

    // The assertion above is the point of this test — the rejection message
    // is confirmed. Closing the dialog is just cleanup, not essential: the
    // modal panel is taller than the viewport here and its Cancel button
    // never scrolls into reach, so dismiss via Escape instead of chasing it.
    await page.keyboard.press('Escape')
  })

  test('a tenant_admin can resolve the same over-threshold refund', async ({ page }) => {
    const REFUND_AMOUNT_NGN = '500000'

    await switchRole(page, 'tenant_admin')
    await goToViaNav(page, /^claims$/i)
    await page.getByPlaceholder(/claim id, customer, container/i).fill('DC-')
    await settleNetwork(page)
    await page.waitForTimeout(300)

    const row = dataRows(page).filter({ hasText: /under inspection/i }).first()
    test.skip((await row.count()) === 0, 'No under-inspection claim found — run the prior tests first')
    await row.getByRole('button', { name: /start inspection|complete|resolve|^view$/i }).click()
    await expect(page.getByText('Claim details')).toBeVisible()

    const resolveBtn = page.getByRole('button', { name: /resolve claim/i })
    test.skip(!(await resolveBtn.isVisible().catch(() => false)), 'Claim not resolvable in its current state')
    await resolveBtn.click()

    const resolveDialog = page.getByRole('dialog')
    await expect(resolveDialog.getByRole('heading', { name: 'Resolve claim' })).toBeVisible()
    await resolveDialog.getByRole('button', { name: /^refund/i }).click()
    await resolveDialog.getByLabel(/amount/i).fill(REFUND_AMOUNT_NGN)
    await resolveDialog.getByLabel(/reason/i).fill('e2e test — admin-approved high-value refund')
    await resolveDialog.getByRole('button', { name: /^resolve claim$/i }).click()

    await expect(resolveDialog).not.toBeVisible({ timeout: 10_000 })
    // "Resolved" appears both as the status badge and in the progress-step
    // list — either confirms the resolution, so just check one exists.
    await expect(page.getByText(/resolved/i).first()).toBeVisible()
  })
})

test.describe('refund review, approve, and reject', () => {
  test('accounts review passes, then tenant_admin approves', async ({ page }) => {
    await switchRole(page, 'nigeria_office_staff')
    await goToViaNav(page, /^refunds$/i)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const row = dataRows(page).filter({ hasText: /pending review/i }).first()
    test.skip((await row.count()) === 0, 'No pending_review refund found — run the claims tests first')
    await row.getByRole('button', { name: /^view$/i }).click()
    await expect(page).toHaveURL(/\/refunds\//)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const reviewBtn = page.getByRole('button', { name: /accounts review/i })
    if (await reviewBtn.isVisible().catch(() => false)) {
      await reviewBtn.click()
      const reviewDialog = page.getByRole('dialog')
      await expect(reviewDialog.getByRole('heading', { name: 'Accounts review' })).toBeVisible()
      // "Debt check passed" is the default selection.
      await reviewDialog.getByLabel(/review notes/i).fill('e2e test — no outstanding debt found')
      await reviewDialog.getByRole('button', { name: /advance to approval/i }).click()
      await expect(reviewDialog).not.toBeVisible({ timeout: 10_000 })
    }

    // ₦500,000 exceeds the staff limit — approvalLevel is head_of_finance,
    // so nigeria_office_staff cannot approve; switch to tenant_admin.
    await switchRole(page, 'tenant_admin')
    await goToViaNav(page, /^refunds$/i)
    const pendingApprovalRow = dataRows(page).filter({ hasText: /pending approval/i }).first()
    test.skip((await pendingApprovalRow.count()) === 0, 'No pending_approval refund found')
    await pendingApprovalRow.getByRole('button', { name: /^view$/i }).click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const approveBtn = page.getByRole('button', { name: /^approve$/i })
    test.skip(!(await approveBtn.isVisible().catch(() => false)), 'No approvable refund in this state')
    await approveBtn.click()

    const approveDialog = page.getByRole('dialog')
    await expect(approveDialog.getByRole('heading', { name: 'Approve refund' })).toBeVisible()
    const confirmBtn = approveDialog.getByRole('button', { name: /confirm approval/i })
    await expect(confirmBtn).toBeEnabled()
    await confirmBtn.click()

    await expect(approveDialog).not.toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/approved|processed/i).first()).toBeVisible()
  })

  test('rejecting a refund at accounts review records the reason', async ({ page }) => {
    await switchRole(page, 'nigeria_office_staff')
    await goToViaNav(page, /^refunds$/i)

    const row = dataRows(page).filter({ hasText: /pending review/i }).first()
    test.skip((await row.count()) === 0, 'No pending_review refund found')
    await row.getByRole('button', { name: /^view$/i }).click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const rejectBtn = page.getByRole('button', { name: /^reject$/i })
    test.skip(!(await rejectBtn.isVisible().catch(() => false)), 'No rejectable refund in this state')
    await rejectBtn.click()

    const rejectDialog = page.getByRole('dialog')
    await expect(rejectDialog.getByRole('heading', { name: 'Reject refund request' })).toBeVisible()
    await rejectDialog.getByLabel(/rejection reason/i).fill('e2e test — customer did not provide bank details')
    await rejectDialog.getByRole('button', { name: /confirm rejection/i }).click()

    await expect(rejectDialog).not.toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/^rejected$/i).first()).toBeVisible()
    await expect(page.getByText('e2e test — customer did not provide bank details')).toBeVisible()
  })
})
