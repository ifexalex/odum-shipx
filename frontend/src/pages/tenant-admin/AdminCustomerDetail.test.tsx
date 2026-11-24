/**
 * 3.6 / audit gap A2 — tabbed Customer Profile: hero, Profile/Shipments/
 * Billing/Claims tabs fed by customer-scoped queries, and the GDPR flows
 * folded into the Data & privacy tab (ANONYMISE friction preserved).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { billingApi } from '../../api/billing'
import { claimsApi } from '../../api/claims'
import { packingListApi } from '../../api/packingList'
import { customersApi } from '../../api/tenantManagement'
import { AdminCustomerDetail } from './AdminCustomerDetail'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    customersApi: { ...original.customersApi, get: vi.fn(), anonymise: vi.fn(), export: vi.fn() },
  }
})
vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return { ...original, billingApi: { ...original.billingApi, listForCustomer: vi.fn() } }
})
vi.mock('../../api/claims', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/claims')>()
  return { ...original, claimsApi: { ...original.claimsApi, list: vi.fn() } }
})
vi.mock('../../api/packingList', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/packingList')>()
  return { ...original, packingListApi: { ...original.packingListApi, list: vi.fn() } }
})

const CUSTOMER = {
  id: 'c1',
  tenant_id: 't1',
  name: 'Ngozi Okonkwo',
  phone: '+2348012345678',
  email: 'ngozi@example.com',
  whatsapp: null,
  address: '14 Adeniran Ogunsanya St, Surulere',
  anonymised_at: null,
  user_id: null,
  consent_given_at: '2026-02-14T00:00:00Z',
  notification_consent: ['sms', 'whatsapp'],
  created_at: '2026-02-14T00:00:00Z',
}

const PL = {
  id: 'pl1',
  reference: 'PL-20260410-008',
  customer_id: 'c1',
  container_id: 'cont1',
  container_number: 'MSCU1234567',
  status: 'approved',
  carton_count: 4,
  total_cbm: '0.560',
  items: [],
  created_at: '2026-04-10T11:42:00Z',
}

const BILLING = {
  id: 'b1',
  invoice_number: 'BL-20260415-001',
  customer_id: 'c1',
  customer_name: 'Ngozi Okonkwo',
  container_id: 'cont1',
  container_number: 'MSCU1234567',
  total_cbm: '0.56',
  cbm_rate_usd: '45',
  dollar_rate: '1550',
  subtotal_usd: '25.2',
  subtotal_ngn: '39060',
  misc_fees: [],
  misc_fees_ngn: 0,
  adjustments_ngn: '0',
  carryover_ngn: 0,
  storage_fees_ngn: 0,
  total_due_ngn: '73704',
  total_paid_ngn: '49352',
  outstanding_ngn: '24352',
  payment_status: 'partially_paid',
  released_with_outstanding: false,
  billed_at: null,
  payments: [],
  carryovers: [],
  _active_disputes: [],
}

const CLAIM = {
  id: 'dc1',
  reference: 'DC-20260728-001',
  status: 'filed',
  container_id: null,
  container_number: 'MSCU1234567',
  customer_id: 'c1',
  customer_name: 'Ngozi Okonkwo',
  description: 'Water damage',
  inspection_method: null,
  cartons_affected: ['C1', 'C2'],
  upload_urls: null,
  created_at: '2026-06-01T10:00:00Z',
}

function makeCtx(readOnly = false): SessionContextValue {
  const session: Session = {
    tenantId: 't1',
    userId: 'u1',
    name: 'Amara',
    role: 'tenant_admin',
    roles: ['tenant_admin'],
    isPlatformAdmin: false,
    impersonatedBy: readOnly ? 'p1' : null,
    sessionId: null,
    readOnly,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
  return {
    session,
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
}

function renderPage() {
  return render(
    withQuery(
      <SessionContext.Provider value={makeCtx()}>
        <MemoryRouter initialEntries={['/admin/customers/c1']}>
          <Routes>
            <Route path="/admin/customers/:id" element={<AdminCustomerDetail />} />
            <Route path="/packing-lists/:id" element={<div>PL detail page</div>} />
            <Route path="/billing/:id" element={<div>Billing detail page</div>} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>,
    ),
  )
}

describe('AdminCustomerDetail — tabbed profile (A2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(customersApi.get).mockResolvedValue(CUSTOMER)
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [PL],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    vi.mocked(billingApi.listForCustomer).mockResolvedValue([BILLING] as never)
    vi.mocked(claimsApi.list).mockResolvedValue({
      data: [CLAIM],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
  })

  it('renders the hero with status badge and contact meta, plus lifetime stats', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Ngozi Okonkwo' })).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText(/Customer since 14 Feb 2026/)).toBeInTheDocument()

    // Profile-tab stats derived from the customer-scoped queries
    expect(await screen.findByText('Total shipments')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('₦73,704')).toBeInTheDocument()) // total billed
    expect(screen.getByText('₦24,352')).toBeInTheDocument() // outstanding
  })

  it('fetches related records scoped to this customer', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Ngozi Okonkwo' })
    expect(packingListApi.list).toHaveBeenCalledWith(expect.objectContaining({ customer_id: 'c1' }))
    expect(claimsApi.list).toHaveBeenCalledWith(expect.objectContaining({ customer_id: 'c1' }))
    expect(billingApi.listForCustomer).toHaveBeenCalledWith('c1')
  })

  it('Shipments tab lists the customer packing lists and links to detail', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Ngozi Okonkwo' })

    await userEvent.click(screen.getByRole('tab', { name: 'Shipments' }))
    expect(await screen.findByText('PL-20260410-008')).toBeInTheDocument()

    await userEvent.click(screen.getByText('PL-20260410-008'))
    expect(await screen.findByText('PL detail page')).toBeInTheDocument()
  })

  it('Billing tab shows records with paid/outstanding columns', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Ngozi Okonkwo' })

    await userEvent.click(screen.getByRole('tab', { name: 'Billing' }))
    expect(await screen.findByText('BL-20260415-001')).toBeInTheDocument()
    // Appears in both the "Total paid" stat card and the table row
    expect(screen.getAllByText('₦49,352').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Partly paid')).toBeInTheDocument()
  })

  it('Claims tab lists the customer claims', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Ngozi Okonkwo' })

    await userEvent.click(screen.getByRole('tab', { name: 'Claims' }))
    expect(await screen.findByText('DC-20260728-001')).toBeInTheDocument()
  })

  it('Data & privacy tab holds the GDPR flows with the ANONYMISE friction intact', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Ngozi Okonkwo' })

    await userEvent.click(screen.getByRole('tab', { name: 'Data & privacy' }))
    expect(screen.getByText('Export data (GDPR)')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Erase data (GDPR)'))
    const dialog = screen.getByRole('dialog')
    const eraseBtn = within(dialog).getByRole('button', { name: /erase data permanently/i })
    expect(eraseBtn).toBeDisabled()

    // Wrong case must NOT enable — exact "ANONYMISE" required
    const input = within(dialog).getByPlaceholderText('ANONYMISE')
    await userEvent.type(input, 'anonymise')
    expect(within(dialog).getByRole('button', { name: /erase data permanently/i })).toBeDisabled()

    await userEvent.clear(input)
    await userEvent.type(input, 'ANONYMISE')
    expect(within(dialog).getByRole('button', { name: /erase data permanently/i })).toBeEnabled()
  })
})
