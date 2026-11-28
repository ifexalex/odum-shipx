/**
 * 3.1 / audit gap B3 — tenant admin dashboard: greeting hero + summary line,
 * admin-only Active-customers / Open-claims stats, and a recent-containers table.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { billingApi, disputeApi } from '../../api/billing'
import { claimsApi } from '../../api/claims'
import { manifestApi } from '../../api/manifest'
import { packingListApi } from '../../api/packingList'
import { releaseNotesApi } from '../../api/releaseNotes'
import { customersApi } from '../../api/tenantManagement'
import { containersApi } from '../../api/tracking'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { Dashboard } from './Dashboard'

vi.mock('../../api/tracking', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tracking')>()
  return { ...original, containersApi: { ...original.containersApi, list: vi.fn(), stats: vi.fn() } }
})
vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return {
    ...original,
    billingApi: { ...original.billingApi, list: vi.fn(), recentPayments: vi.fn(), stats: vi.fn() },
    disputeApi: { ...original.disputeApi, list: vi.fn() },
  }
})
vi.mock('../../api/manifest', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/manifest')>()
  return { ...original, manifestApi: { ...original.manifestApi, list: vi.fn() } }
})
vi.mock('../../api/releaseNotes', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/releaseNotes')>()
  return { ...original, releaseNotesApi: { ...original.releaseNotesApi, list: vi.fn() } }
})
vi.mock('../../api/packingList', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/packingList')>()
  return { ...original, packingListApi: { ...original.packingListApi, list: vi.fn() } }
})
vi.mock('../../api/claims', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/claims')>()
  return { ...original, claimsApi: { ...original.claimsApi, list: vi.fn(), stats: vi.fn() } }
})
vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, customersApi: { ...original.customersApi, list: vi.fn(), stats: vi.fn() } }
})
// PlanUsagePanel makes its own quota call — stub it out of this page test.
vi.mock('../../shell/PlanUsagePanel', () => ({ PlanUsagePanel: () => null }))

const CONTAINER = {
  id: 'c1', tenant_id: 't1', container_number: 'MSCU1234567', parcel_number: null,
  origin: 'Guangzhou', destination: 'Lagos', ship_date: null, estimated_arrival_date: '2026-08-14',
  actual_arrival_date: null, status: 'in_transit', notes: null, created_by: 's1',
  created_at: '2026-07-01', updated_at: '2026-07-01', vessel_name: null, voyage_number: null,
  shipping_line: null, seal_number: null, container_type: null, capacity_cbm: null, recommended_cbm: null, created_by_name: null,
}

function renderDashboard(role: Session['role'] = 'tenant_admin') {
  const session: Session = {
    tenantId: 't1', userId: 'u1', name: 'Amara Okafor', role, roles: [role],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null,
    readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
  const ctx: SessionContextValue = {
    session, status: 'authenticated',
    login: vi.fn(), logout: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider value={ctx}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

describe('Dashboard (B3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [CONTAINER],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    } as never)
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: true, next_cursor: 'x', total_count: 142 } },
    } as never)
    vi.mocked(claimsApi.list).mockResolvedValue({
      data: [{ status: 'filed' }, { status: 'under_inspection' }, { status: 'resolved' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 3 } },
    } as never)
    // Server-side aggregates that now drive the stat cards + summary line.
    vi.mocked(containersApi.stats).mockResolvedValue({
      total: 1, loading: 0, sealed: 0, in_transit: 1, arrived: 0, customs_clearance: 0,
      cleared: 0, at_warehouse: 0, fully_released: 0, cancelled: 0, cleared_30d: 0,
    })
    vi.mocked(billingApi.stats).mockResolvedValue({
      outstanding_ngn: '0', paid_this_month_ngn: '0', overdue: 0, total: 0,
      unpaid: 0, partially_paid: 0, paid: 0, overpaid: 0, waived: 0, released_with_outstanding: 0,
    })
    vi.mocked(claimsApi.stats).mockResolvedValue({
      total: 3, open: 2, under_inspection: 1, resolved_30d: 0,
      filed: 1, pending_resolution: 0, resolved: 1, closed: 0,
    })
    vi.mocked(customersApi.stats).mockResolvedValue({
      total: 142, active: 142, anonymised: 0, with_whatsapp: 0, shipments: 0,
    })
    const emptyList = {
      data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    } as never
    vi.mocked(packingListApi.list).mockResolvedValue(emptyList)
    vi.mocked(manifestApi.list).mockResolvedValue(emptyList)
    vi.mocked(disputeApi.list).mockResolvedValue(emptyList)
    vi.mocked(releaseNotesApi.list).mockResolvedValue(emptyList)
    vi.mocked(billingApi.recentPayments).mockResolvedValue([])
  })

  it('greets the admin by first name with a container summary line', async () => {
    renderDashboard()
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByText(/, Amara$/)).toBeInTheDocument()
    // The summary facts arrive with the container stats, a tick after the greeting.
    expect(await screen.findByText('1 in transit')).toBeInTheDocument()
    expect(screen.getByText('0 awaiting customs')).toBeInTheDocument()
    expect(screen.getByText('0 ready for pickup')).toBeInTheDocument()
  })

  it('shows admin-only active-customers and open-claims stats', async () => {
    renderDashboard()
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })
    await waitFor(() => expect(screen.getByText('142')).toBeInTheDocument())   // customers
    await waitFor(() => expect(screen.getByText('2')).toBeInTheDocument())     // open claims (filed + under_inspection)
    expect(screen.getByText('Active customers')).toBeInTheDocument()
    expect(screen.getByText('Open claims')).toBeInTheDocument()
  })

  it('shows the Outstanding invoices card (money to chase) for nigeria staff', async () => {
    // Replaced the passive "Recent payments" log with the actionable list of
    // what still needs collecting — oldest unpaid first.
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [
        { id: 'b1', customer_name: 'Ngozi Okonkwo', container_number: 'MSCU1234567', outstanding_ngn: '50000.00', payment_status: 'unpaid' },
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)

    renderDashboard('nigeria_office_staff')
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })

    await waitFor(() => expect(screen.getByText('Outstanding invoices')).toBeInTheDocument())
    expect(screen.getByText('₦50,000')).toBeInTheDocument()
  })

  it('renders the recent-containers table for admins', async () => {
    renderDashboard()
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })
    expect(screen.getByText('Recent containers')).toBeInTheDocument()
    expect(await screen.findByText('MSCU1234567')).toBeInTheDocument()
  })

  it('does not show the admin-only extras for nigeria staff', async () => {
    renderDashboard('nigeria_office_staff')
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })
    expect(screen.queryByText('Active customers')).toBeNull()
    expect(screen.queryByText('Recent containers')).toBeNull()
    expect(customersApi.list).not.toHaveBeenCalled()
  })

  // P2-5 — §6.1 Nigeria ops action queues
  it('shows the manifest-verification queue, disputes queue, and outstanding invoices for nigeria staff', async () => {
    vi.mocked(manifestApi.list).mockResolvedValue({
      data: [
        // Arrived in NG → in the queue
        { id: 'm1', container_number: 'MSCU1234567', container_status: 'arrived', total_cartons: 22, verification_status: 'pending' },
        // Still at sea → filtered out
        { id: 'm2', container_number: 'HLBU9384712', container_status: 'in_transit', total_cartons: 8, verification_status: 'pending' },
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    } as never)
    vi.mocked(disputeApi.list).mockResolvedValue({
      data: [{ id: 'd1', original_cbm: '2.14', status: 'submitted', submitted_at: '2026-07-15T10:00:00Z' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [{ id: 'b1', customer_name: 'Ngozi Okonkwo', container_number: 'ACME0001', outstanding_ngn: '50000.00', payment_status: 'partially_paid' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    vi.mocked(releaseNotesApi.list).mockResolvedValue({
      data: [{ id: 'rn1' }, { id: 'rn2' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    } as never)

    renderDashboard('nigeria_office_staff')
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })

    await waitFor(() => expect(screen.getByText('Containers awaiting manifest verification')).toBeInTheDocument())
    // Only the arrived container is queued — the in-transit one is filtered out.
    // (MSCU1234567 also appears in the pipeline table, hence getAllByText.)
    expect(screen.getAllByText('MSCU1234567').length).toBeGreaterThan(0)
    expect(screen.queryByText('HLBU9384712')).toBeNull()

    expect(screen.getByText('CBM disputes need response')).toBeInTheDocument()
    expect(screen.getByText('Outstanding invoices')).toBeInTheDocument()
    expect(screen.getByText('₦50,000')).toBeInTheDocument()
    expect(screen.getByText('Ready for pickup')).toBeInTheDocument()
  })

  // §3.1 bottom row — QuickActionCards replaced the old generic nav-card stacks
  it('shows admin quick actions instead of the old nav stacks', async () => {
    renderDashboard()
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })
    expect(screen.getByText('Quick actions')).toBeInTheDocument()
    // Card title + CTA both carry the label — assert the heading
    expect(screen.getByRole('heading', { name: 'Add customer' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Invite staff' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Review dollar markup' })).toBeInTheDocument()
    expect(screen.queryByText('Operations')).toBeNull()
    expect(screen.queryByText('Billing & Claims')).toBeNull()
  })

  // §6.1 bottom row — "Awaiting pickup" (active release notes: goods released,
  // not yet collected) replaced the passive "Incoming containers" ETA list.
  it('shows the Awaiting pickup card for nigeria staff', async () => {
    vi.mocked(releaseNotesApi.list).mockResolvedValue({
      data: [
        { id: 'rn1', reference_number: 'RN-001', customer_name: 'Chidi Okafor', container_number: 'ACME0007', total_cartons_for_customer: 12, is_on_credit: true },
        { id: 'rn2', reference_number: 'RN-002', customer_name: 'Ada Eze', container_number: 'ACME0008', total_cartons_for_customer: 4, is_on_credit: false },
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    } as never)
    renderDashboard('nigeria_office_staff')
    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })
    await waitFor(() => expect(screen.getByText('Awaiting pickup')).toBeInTheDocument())
    expect(screen.getByText('Chidi Okafor')).toBeInTheDocument()
    expect(screen.getByText('On credit')).toBeInTheDocument()
  })
})
