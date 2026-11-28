/**
 * 2.2 / audit gap B2 — enriched tenant list: status filter chips with counts,
 * search across name/email/slug/id, and the staff seats x/limit column. Filtering, search and paging run on the server
 * (audit PA-02), so these tests check what the page asks the API for.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformApi, type Tenant } from '../../api/tenantManagement'
import { PlatformTenantList } from './PlatformTenantList'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, platformApi: { ...original.platformApi, listTenants: vi.fn(), dashboard: vi.fn() } }
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

function page(data: Tenant[], nextCursor: string | null = null, total = data.length) {
  return { data, meta: { pagination: { has_more: nextCursor !== null, next_cursor: nextCursor, total_count: total } } }
}

describe('PlatformTenantList (B2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // The fake server applies the filters the page sends.
    vi.mocked(platformApi.listTenants).mockImplementation(async (params = {}) => {
      const q = params.q?.toLowerCase()
      const rows = TENANTS.filter(
        (t) =>
          (!params.status || t.status === params.status) &&
          (!q || [t.company_name, t.slug, t.primary_contact_email, t.id].some((v) => v.toLowerCase().includes(q))),
      )
      return page(rows) as never
    })
    vi.mocked(platformApi.dashboard).mockResolvedValue({
      tenants: { active_tenants: 2, suspended_tenants: 1, offboarded_tenants: 0, starter_tenants: 1, business_tenants: 2, enterprise_tenants: 0 },
      total_users: 34,
      total_containers: 0,
    })
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

    // Chip counts are the platform totals from the dashboard route, not the rows on screen.
    const suspendedChip = (await screen.findAllByText('Suspended')).find((el) => el.closest('button'))!
    expect(within(suspendedChip.closest('button')!).getByText('1')).toBeInTheDocument()
    await userEvent.click(suspendedChip)
    await waitFor(() => expect(screen.queryByText('Acme Logistics')).toBeNull())
    expect(screen.getByText('Tin Can Logistics')).toBeInTheDocument()
    expect(platformApi.listTenants).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'suspended', limit: 50 }))
  })

  it('searches across name, email, and slug', async () => {
    renderPage()
    await screen.findByText('Acme Logistics')

    await userEvent.type(screen.getByPlaceholderText(/search by name/i), 'ezefreight')
    await waitFor(() =>
      expect(platformApi.listTenants).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'ezefreight' })),
    )
    expect(await screen.findByText('Eze Freight')).toBeInTheDocument()
    expect(screen.queryByText('Acme Logistics')).toBeNull()
  })

  it('reaches tenants past the first page (PA-02: the list used to stop at 50)', async () => {
    const first = Array.from({ length: 50 }, (_, i) => tenant({ id: `tnt-page1-${i}`, company_name: `Tenant ${i}`, slug: `t${i}` }))
    const last = tenant({ id: 'tnt-page2-0', company_name: 'The fifty-first tenant', slug: 't50' })
    vi.mocked(platformApi.listTenants).mockImplementation(async (params = {}) =>
      (params.cursor === 'page-2' ? page([last], null, 51) : page(first, 'page-2', 51)) as never,
    )
    renderPage()
    await screen.findByText('Tenant 0')
    expect(screen.queryByText('The fifty-first tenant')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /load more/i }))
    expect(await screen.findByText('The fifty-first tenant')).toBeInTheDocument()
    expect(platformApi.listTenants).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'page-2' }))
  })

  it('opens a tenant from its row', async () => {
    renderPage()
    await screen.findByText('Acme Logistics')
    const firstRow = screen.getByText('Acme Logistics').closest('tr')!
    await userEvent.click(within(firstRow).getAllByRole('button')[0]!)
    expect(await screen.findByText('Tenant detail')).toBeInTheDocument()
  })
})
