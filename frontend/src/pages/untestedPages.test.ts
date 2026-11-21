/**
 * Ratchet for audit OPS-03: the list of pages with no test may only shrink.
 *
 * A page here has no sibling `*.test.tsx`. On 2026-11-17 the money-moving ones (MyBilling, RefundRequest,
 * CarryoverLedger) and the platform tenant page got tests; what is left is mostly auth screens, print views,
 * marketing and small parts. A new page must come with a test: this fails if one does not. When a listed page gets a
 * test, delete it from the list (this fails until you do, so the list stays true).
 */
import { describe, expect, it } from 'vitest'

const PAGES = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** Pages known to have no test, with what they are. Shrink this; do not grow it. */
const KNOWN_UNTESTED: Record<string, string> = {
  './auth/ActivateScreen.tsx': 'account activation (Cognito/Entra flows; covered by e2e smoke)',
  './auth/AuthCallback.tsx': 'OAuth redirect landing',
  './auth/AuthShell.tsx': 'layout for the auth screens',
  './auth/ForgotPasswordScreen.tsx': 'password reset request',
  './auth/InviteClaimScreen.tsx': 'customer invite claim',
  './auth/ResetPasswordScreen.tsx': 'password reset',
  './customer/CustomerStepper.tsx': 'shipment progress strip (rendered in MyShipments tests)',
  './customer/PaymentFailed.tsx': 'static "payment failed" page',
  './customer/ReleaseNoteCard.tsx': 'release note summary card',
  './marketing/LandingPage.tsx': 'marketing page',
  './nigeria/EvidenceUploader.tsx': 'claim evidence upload widget',
  './platform/CreateTenantPage.tsx': 'tenant provisioning form',
  './platform/PlatformAuditLog.tsx': 'cross-tenant audit log',
  './print/PrintPackingList.tsx': 'print view',
  './staff/StaffProfile.tsx': 'staff profile',
  './tenant-admin/NotificationTemplates.tsx': 'message template editor',
  './tenant-admin/RoleCheckboxList.tsx': 'role picker',
}

const pages = Object.keys(PAGES).filter((path) => !path.endsWith('.test.tsx'))

/**
 * A large page's parts live in a folder named after it (FE-07): `./nigeria/billingDetail/RecordPaymentModal.tsx`
 * belongs to `./nigeria/BillingDetail.tsx`, which renders it, so the page's test covers it.
 */
function ownerTest(path: string): string | null {
  const match = /^(\.\/[^/]+)\/([a-z][A-Za-z]*)\/[^/]+\.tsx$/.exec(path)
  if (!match) return null
  const [, area = '', folder = ''] = match
  return `${area}/${folder.charAt(0).toUpperCase()}${folder.slice(1)}.test.tsx`
}

const untested = pages.filter((path) => {
  if (path.replace(/\.tsx$/, '.test.tsx') in PAGES) return false
  const owner = ownerTest(path)
  return !(owner && owner in PAGES)
})

describe('pages without tests (OPS-03 ratchet)', () => {
  it('finds the pages', () => {
    expect(pages.length).toBeGreaterThan(80)
  })

  it('has no untested page beyond the known list: a new page comes with a test', () => {
    expect(untested.filter((path) => !(path in KNOWN_UNTESTED))).toEqual([])
  })

  it('lists no page that now has a test, or that no longer exists', () => {
    expect(Object.keys(KNOWN_UNTESTED).filter((path) => !untested.includes(path))).toEqual([])
  })
})
