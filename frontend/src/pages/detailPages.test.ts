/**
 * FD-19: every record page uses the one detail layout (`DetailPage`): header, notices, progress, sections and a
 * summary rail. Its sections put their heading inside their card (`Section`).
 */
import { describe, expect, it } from 'vitest'

const PAGES = import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

const RECORD_PAGES = [
  './china/ContainerDetail.tsx',
  './china/DisputeDetail.tsx',
  './china/PackingListDetail.tsx',
  './customer/MyBillingDetail.tsx',
  './customer/MyClaimDetail.tsx',
  './customer/MyReleaseNote.tsx',
  './customer/MyShipmentDetail.tsx',
  './nigeria/BillingDetail.tsx',
  './nigeria/ClaimDetail.tsx',
  './nigeria/ManifestDetail.tsx',
  './nigeria/RefundDetail.tsx',
  './nigeria/ReleaseNoteDetail.tsx',
  './platform/PlatformTenantDetail.tsx',
  './tenant-admin/AdminCustomerDetail.tsx',
  './tenant-admin/StaffUserDetail.tsx',
]

describe('one detail layout (FD-19)', () => {
  it.each(RECORD_PAGES)('%s uses DetailPage', (path) => {
    expect(PAGES[path], `${path} is not a page`).toBeDefined()
    expect(PAGES[path]).toMatch(/<DetailPage\b/)
  })

  it('the staff and customer invoices share one breakdown', () => {
    for (const path of ['./nigeria/BillingDetail.tsx', './customer/MyBillingDetail.tsx']) {
      expect(PAGES[path]).toMatch(/<InvoiceBreakdown\b/)
    }
  })
})
