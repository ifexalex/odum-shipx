/**
 * 2.2 / audit gap B2 — enriched tenant list: status filter chips with counts,
 * search across name/email/slug/id, and the users x/limit column.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformApi, type Tenant } from '../../api/tenantManagement'
import { PlatformTenantList } from './PlatformTenantList'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, platformApi: { ...original.platformApi, listTenants: vi.fn() } }
})

function tenant(overrides: Partial<Tenant>): Tenant {
  return {
    id: 'tnt-00000000-1111',
    company_name: 'Acme Logistics',
    slug: 'acme',
    primary_contact_email: 'amara@acme.com',
    primary_contact_phone: null,
    subscription_tier: 'business',
    status: 'active',
    created_at: '2026-01-14T00:00:00Z',
    offboarded_at: null,
    reactivated_at: null,
    user_count: 24,
    users_limit: 50,
    ...overrides,
  }
}

const TENANTS = [
  tenant({ id: 'tnt-acme-0001', company_name: 'Acme Logistics', slug: 'acme', status: 'active', user_count: 24, users_limit: 50 }),
  tenant({ id: 'tnt-eze-0002', company_name: 'Eze Freight', slug: 'eze', primary_contact_email: 'ngozi@ezefreight.ng', status: 'active', subscription_tier: 'starter', user_count: 10, users_limit: 10 }),
  tenant({ id: 'tnt-tincan-03', company_name: 'Tin Can Logistics', slug: 'tincan', status: 'suspended', user_count: 0, users_limit: 50 }),
]

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/platform/tenants']}>
        <Routes>
          <Route path="/platform/tenants" element={<PlatformTenantList />} />
          <Route path="/platform/tenants/:id" element={<div>Tenant detail</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PlatformTenantList (B2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(platformApi.listTenants).mockResolvedValue({
      data: TENANTS,
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 3 } },
    } as never)
  })

  it('renders users x/limit and the mono id prefix', async () => {
    renderPage()
    expect(await screen.findByText('Acme Logistics')).toBeInTheDocument()
    expect(screen.getByText('24 / 50')).toBeInTheDocument()
    expect(screen.getByText('10 / 10')).toBeInTheDocument()
    expect(screen.getByText('tnt-acme…')).toBeInTheDocument()
  })

  it('filters by status chip with counts', async () => {
    renderPage()
    await screen.findByText('Acme Logistics')

    // Suspended chip (a button) — distinct from the row status badge
    const suspendedChip = screen.getAllByText('Suspended').find((el) => el.closest('button'))!
    await userEvent.click(suspendedChip)
    expect(screen.getByText('Tin Can Logistics')).toBeInTheDocument()
    expect(screen.queryByText('Acme Logistics')).toBeNull()
    expect(screen.getByText(/Showing 1 of 3/)).toBeInTheDocument()
  })

  it('searches across name, email, and slug', async () => {
    renderPage()
    await screen.findByText('Acme Logistics')

    await userEvent.type(screen.getByPlaceholderText(/search by name/i), 'ezefreight')
    expect(screen.getByText('Eze Freight')).toBeInTheDocument()
    expect(screen.queryByText('Acme Logistics')).toBeNull()
  })

  it('opens a tenant on view', async () => {
    renderPage()
    await screen.findByText('Acme Logistics')
    const firstRow = screen.getByText('Acme Logistics').closest('tr')!
    await userEvent.click(within(firstRow).getByText('View'))
    expect(await screen.findByText('Tenant detail')).toBeInTheDocument()
  })
})
