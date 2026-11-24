import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { quotaApi, type TenantQuota } from '../api/tenantManagement'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session, UserRole } from '../auth/types'
import { ShellNotice } from './ShellNotice'

vi.mock('../api/tenantManagement', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/tenantManagement')>()),
  quotaApi: { getMyQuota: vi.fn() },
}))

const quota = (used: number, max = 10): TenantQuota =>
  ({
    tenant_id: 't1',
    period: '2026-11',
    subscription_tier: 'starter',
    limits: {
      users: { used, max },
      containers_per_month: { used: 1, max: 50 },
      storage_gb: { used: 1, max: 10 },
    },
  }) as unknown as TenantQuota

function renderNotice(role: UserRole, announcement: { id: string; title: string; body: null } | null = null, readOnly = false) {
  const session = { tenantId: 't1', userId: 'u1', name: null, role, roles: [role], isPlatformAdmin: false, readOnly } as unknown as Session
  const ctx = { session, status: 'authenticated' } as unknown as SessionContextValue
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider value={ctx}>
        <MemoryRouter>
          <ShellNotice announcement={announcement} />
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  sessionStorage.clear()
  vi.mocked(quotaApi.getMyQuota).mockResolvedValue(quota(14))
})

describe('the plan-limit notice (FD-16)', () => {
  it('is one line for the tenant admin, with a link to the plan', async () => {
    renderNotice('tenant_admin')
    expect(await screen.findByText(/Users: 14 of 10\. You have reached your Starter plan’s limit\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View plan' })).toHaveAttribute('href', '/dashboard#plan')
  })

  it('is not shown to staff who cannot change the plan', async () => {
    renderNotice('nigeria_office_staff')
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/plan’s limit/)).toBeNull()
  })

  it('warns from 80%', async () => {
    vi.mocked(quotaApi.getMyQuota).mockResolvedValue(quota(8))
    renderNotice('tenant_admin')
    expect(await screen.findByText(/Users: 8 of 10 used, close to your Starter plan’s limit\./)).toBeInTheDocument()
  })

  it('stays dismissed for the session, and comes back when the situation changes', async () => {
    vi.mocked(quotaApi.getMyQuota).mockResolvedValue(quota(8))
    const first = renderNotice('tenant_admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Dismiss the plan-limit notice' }))
    expect(screen.queryByText(/plan’s limit/)).toBeNull()
    first.unmount()

    renderNotice('tenant_admin') // a new page, same warning
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/plan’s limit/)).toBeNull()
  })

  it('shows again once a warning becomes a reached limit', async () => {
    sessionStorage.setItem('shipx_quota_notice_dismissed', 'users:near')
    renderNotice('tenant_admin')
    expect(await screen.findByText(/You have reached/)).toBeInTheDocument()
  })
})

describe('one notice at a time (FD-16)', () => {
  const announcement = { id: 'a1', title: 'Office closed Friday', body: null }

  it('shows the announcement ahead of the plan-limit notice, and the plan notice once it is dismissed', async () => {
    renderNotice('tenant_admin', announcement)
    expect(screen.getByText('Office closed Friday')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/plan’s limit/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(await screen.findByText(/You have reached/)).toBeInTheDocument()
  })

  it('shows nothing here during impersonation: that banner is the one shown', async () => {
    renderNotice('tenant_admin', announcement, true)
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText('Office closed Friday')).toBeNull()
    expect(screen.queryByText(/plan’s limit/)).toBeNull()
  })
})
