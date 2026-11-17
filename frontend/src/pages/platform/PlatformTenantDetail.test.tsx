/**
 * The platform tenant page: the offboarding data export card (audit BE-10), and the tabs that read through hooks.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { platformApi, type OffboardingExport, type Tenant } from '../../api/tenantManagement'
import { useSession } from '../../auth/useSession'
import { withQuery } from '../../test/queryWrapper'
import { PlatformTenantDetail } from './PlatformTenantDetail'

vi.mock('../../auth/useSession')
vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    platformApi: {
      ...original.platformApi,
      getTenant: vi.fn(),
      tenantUsers: vi.fn(),
      tenantConfig: vi.fn(),
      auditLog: vi.fn(),
      offboardingExport: vi.fn(),
      queueOffboardingExport: vi.fn(),
      offboardingExportLink: vi.fn(),
    },
  }
})

const TENANT: Tenant = {
  id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  company_name: 'Acme Logistics',
  slug: 'acme',
  primary_contact_email: 'ops@acme.test',
  primary_contact_phone: null,
  subscription_tier: 'business',
  status: 'offboarded',
  created_at: '2026-01-14T00:00:00Z',
  offboarded_at: '2026-11-01T09:00:00Z',
  reactivated_at: null,
}

function exportInfo(overrides: Partial<OffboardingExport>): OffboardingExport {
  return {
    tenant_status: 'offboarded',
    status: 'completed',
    export_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    requested_at: '2026-11-01T09:00:00Z',
    completed_at: '2026-11-01T10:00:00Z',
    size_bytes: 2_621_440,
    sha256: 'c'.repeat(64),
    row_count: 18_250,
    attempts: 1,
    max_attempts: 3,
    retrying: false,
    can_queue: false,
    deletion_scheduled_at: '2026-01-30T09:00:00Z',
    ...overrides,
  }
}

function renderPage(tenant: Tenant = TENANT) {
  vi.mocked(platformApi.getTenant).mockResolvedValue(tenant)
  return render(
    withQuery(
      <MemoryRouter initialEntries={[`/platform/tenants/${tenant.id}`]}>
        <Routes>
          <Route path="/platform/tenants/:id" element={<PlatformTenantDetail />} />
        </Routes>
      </MemoryRouter>,
    ),
  )
}

const assign = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useSession).mockReturnValue({ startImpersonation: vi.fn() } as unknown as ReturnType<typeof useSession>)
  vi.stubGlobal('location', { ...window.location, assign })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PlatformTenantDetail data export (BE-10)', () => {
  it('shows a ready archive with its size, records, checksum and deletion date', async () => {
    vi.mocked(platformApi.offboardingExport).mockResolvedValue(exportInfo({}))
    renderPage()
    expect(await screen.findByText('Ready')).toBeInTheDocument()
    expect(screen.getByText('2.5 MB')).toBeInTheDocument()
    expect(screen.getByText('18,250')).toBeInTheDocument()
    expect(screen.getByText('c'.repeat(64))).toBeInTheDocument()
    expect(screen.getByText('Data deleted on')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Queue export' })).toBeNull()
  })

  it('downloads through a fresh link, not a stored one', async () => {
    vi.mocked(platformApi.offboardingExport).mockResolvedValue(exportInfo({}))
    vi.mocked(platformApi.offboardingExportLink).mockResolvedValue({
      download_url: 'https://storage.test/signed?sig=1',
      expires_at: '2026-11-17T12:05:00Z',
      filename: 'shipx-export-acme-20261101.zip',
      size_bytes: 2_621_440,
      sha256: 'c'.repeat(64),
    })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Download archive' }))
    expect(platformApi.offboardingExportLink).toHaveBeenCalledWith(TENANT.id)
    expect(assign).toHaveBeenCalledWith('https://storage.test/signed?sig=1')
  })

  it('says why a download could not start', async () => {
    vi.mocked(platformApi.offboardingExport).mockResolvedValue(exportInfo({}))
    vi.mocked(platformApi.offboardingExportLink).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'x', status: 422, detail: 'The export is not ready yet.', error_code: 'BUSINESS_RULE_VIOLATION' }, null),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Download archive' }))
    expect(await screen.findByText('The export is not ready yet.')).toBeInTheDocument()
    expect(assign).not.toHaveBeenCalled()
  })

  it('says a queued export runs within the hour and offers no download', async () => {
    vi.mocked(platformApi.offboardingExport).mockResolvedValue(
      exportInfo({ status: 'pending', completed_at: null, size_bytes: null, sha256: null, row_count: null, attempts: 0 }),
    )
    renderPage()
    expect(await screen.findByText('Queued')).toBeInTheDocument()
    expect(screen.getByText(/runs within the hour/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Download archive' })).toBeNull()
  })

  it('says a failed attempt is being retried', async () => {
    vi.mocked(platformApi.offboardingExport).mockResolvedValue(
      exportInfo({ status: 'failed', retrying: true, attempts: 1, completed_at: null, size_bytes: null, sha256: null, row_count: null }),
    )
    renderPage()
    expect(await screen.findByText('Attempt 1 of 3 failed. It is tried again within the hour.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Queue export' })).toBeNull()
  })

  it('lets an admin queue an export that gave up, or one that was never queued', async () => {
    vi.mocked(platformApi.offboardingExport).mockResolvedValue(
      exportInfo({ status: 'none', export_id: null, completed_at: null, size_bytes: null, sha256: null, row_count: null, can_queue: true }),
    )
    vi.mocked(platformApi.queueOffboardingExport).mockResolvedValue(exportInfo({ status: 'pending' }))
    renderPage()
    expect(await screen.findByText('Not queued')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Queue export' }))
    expect(platformApi.queueOffboardingExport).toHaveBeenCalledWith(TENANT.id)
  })

  it('shows no export card for a tenant that has not been offboarded', async () => {
    renderPage({ ...TENANT, status: 'active', offboarded_at: null })
    expect(await screen.findByText('Tenant details')).toBeInTheDocument()
    expect(screen.queryByText('Data export')).toBeNull()
    expect(platformApi.offboardingExport).not.toHaveBeenCalled()
  })
})

describe('PlatformTenantDetail tabs read through hooks (FE-05)', () => {
  it('loads the Users, Configuration and Audit tabs', async () => {
    vi.mocked(platformApi.offboardingExport).mockResolvedValue(exportInfo({}))
    vi.mocked(platformApi.tenantUsers).mockResolvedValue([
      { id: 'u1', email: 'ada@acme.test', full_name: 'Ada Obi', role: 'tenant_admin', status: 'active', locale: 'en' },
    ] as Awaited<ReturnType<typeof platformApi.tenantUsers>>)
    vi.mocked(platformApi.tenantConfig).mockResolvedValue({ branding: { primary_color: '#123456' } })
    vi.mocked(platformApi.auditLog).mockResolvedValue({
      data: [{ id: 'a1', action: 'TENANT_EXPORT_LINK_ISSUED', created_at: '2026-11-17T12:00:00Z', ip_address: '203.0.113.9' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as Awaited<ReturnType<typeof platformApi.auditLog>>)
    renderPage()

    await userEvent.click(await screen.findByRole('tab', { name: 'Users' }))
    expect(await screen.findByText('Ada Obi')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Configuration' }))
    expect(await screen.findByText('{"primary_color":"#123456"}')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Audit log' }))
    expect(await screen.findByText('TENANT EXPORT LINK ISSUED')).toBeInTheDocument()
    expect(platformApi.auditLog).toHaveBeenCalledWith({ tenant_id: TENANT.id, limit: 50 })
  })
})
