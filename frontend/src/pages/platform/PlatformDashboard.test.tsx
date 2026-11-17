/**
 * 2.1 / audit gap B1 — platform dashboard: tenant-health users x/limit column,
 * recent-activity feed from the audit log, and quick-action tiles.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformApi } from '../../api/tenantManagement'
import { PlatformDashboard } from './PlatformDashboard'
import { withQuery } from '../../test/queryWrapper'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    platformApi: { ...original.platformApi, dashboard: vi.fn(), listTenants: vi.fn(), auditLog: vi.fn() },
  }
})

const STATS = {
  tenants: { active_tenants: 10, suspended_tenants: 2, offboarded_tenants: 1, starter_tenants: 4, business_tenants: 5, enterprise_tenants: 4 },
  total_users: 142,
  total_containers: 284,
}

const TENANTS = [
  { id: 'tnt-acme-01', company_name: 'Acme Logistics', slug: 'acme', primary_contact_email: 'a@acme.com', primary_contact_phone: null, subscription_tier: 'business', status: 'active', created_at: '2026-01-14T00:00:00Z', offboarded_at: null, reactivated_at: null, user_count: 24, users_limit: 50 },
]

function renderPage() {
  return render(withQuery(
    <MemoryRouter initialEntries={['/platform/dashboard']}>
      <Routes>
        <Route path="/platform/dashboard" element={<PlatformDashboard />} />
        <Route path="/platform/audit-log" element={<div>Audit log page</div>} />
        <Route path="/platform/tenants/new" element={<div>Onboard tenant page</div>} />
      </Routes>
    </MemoryRouter>,
  ))
}

describe('PlatformDashboard (B1)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(platformApi.dashboard).mockResolvedValue(STATS as never)
    vi.mocked(platformApi.listTenants).mockResolvedValue({
      data: TENANTS,
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    vi.mocked(platformApi.auditLog).mockResolvedValue({
      data: [
        { id: 'a1', action: 'TENANT_SUSPENDED', actor_id: 'p1', target_tenant_id: 'tnt-acme-01', details: null, ip_address: null, created_at: new Date(Date.now() - 3600_000).toISOString() },
        { id: 'a2', action: 'TENANT_CREATED', actor_id: 'p1', target_tenant_id: 'tnt-acme-01', details: null, ip_address: null, created_at: new Date(Date.now() - 7200_000).toISOString() },
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    } as never)
  })

  it('shows the users x/limit column in the tenant-health table', async () => {
    renderPage()
    expect(await screen.findByText('24 / 50')).toBeInTheDocument()
    expect(screen.getByText('24 / 50')).toBeInTheDocument()
  })

  it('renders the recent-activity feed from the audit log', async () => {
    renderPage()
    await screen.findByText('24 / 50')
    await waitFor(() => expect(screen.getByText('TENANT SUSPENDED')).toBeInTheDocument())
    expect(screen.getByText('TENANT CREATED')).toBeInTheDocument()
  })

  it('quick-action tiles navigate', async () => {
    renderPage()
    await screen.findByText('24 / 50')
    await userEvent.click(screen.getByRole('button', { name: /start onboarding/i }))
    expect(await screen.findByText('Onboard tenant page')).toBeInTheDocument()
  })

  it('activity feed footer links to the full audit log', async () => {
    renderPage()
    await screen.findByText('24 / 50')
    await userEvent.click(screen.getByRole('button', { name: /view full audit log/i }))
    expect(await screen.findByText('Audit log page')).toBeInTheDocument()
  })
})
