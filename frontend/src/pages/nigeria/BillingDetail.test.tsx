import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { billingApi, carryoverApi, disputeApi, paymentClaimApi } from '../../api/billing'
import { BillingDetail } from './BillingDetail'

vi.mock('../../api/billing', () => ({
  billingApi: { list: vi.fn(), listForCustomer: vi.fn(), recordPayment: vi.fn(), cancel: vi.fn(), applyCarryover: vi.fn() },
  disputeApi: { list: vi.fn(), acknowledge: vi.fn(), resolve: vi.fn(), reject: vi.fn() },
  carryoverApi: { list: vi.fn(), exempt: vi.fn() },
  paymentClaimApi: { listForBilling: vi.fn(), confirm: vi.fn(), reject: vi.fn(), getEvidenceUrl: vi.fn() },
}))

function makeSession(role = 'nigeria_office_staff', userId = 'u1'): Session {
  return {
    tenantId: 't1',
    userId,
    name: null,
    role: role as Session['role'],
    roles: [role as Session['role']],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
}

function makeCtx(role = 'nigeria_office_staff'): SessionContextValue {
  return {
    session: makeSession(role),
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
  }
}

const BILLING_STUB = {
  id: 'b1',
  invoice_number: 'ACM-INV-0001',
  customer_id: 'cust1',
  customer_name: 'Amara Nnamani',
  customer_phone: '+2348090000001',
  customer_email: 'amara@example.com',
  container_id: 'c1',
  container_number: 'ACME001',
  total_cbm: '2.500000',
  cbm_rate_usd: '45.0000',
  dollar_rate: '1550.0000',
  subtotal_usd: '112.50',
  subtotal_ngn: '174375.00',
  misc_fees: [],
  misc_fees_ngn: 0,
  adjustments_ngn: '0',
  carryover_ngn: 0,
  storage_fees_ngn: 0,
  total_due_ngn: '174375.00',
  total_paid_ngn: '0',
  outstanding_ngn: '174375.00',
  payment_status: 'unpaid' as const,
  released_with_outstanding: false,
  billed_at: null,
  payments: [
    { id: 'p1', amount_ngn: '83700.00', payment_method: 'cash', payment_reference: 'CASH001', confirmed_at: '2026-06-01T09:00:00Z' },
  ],
  carryovers: [],
  _active_disputes: [],
}

const DISPUTE_STUB = {
  id: 'd1',
  billing_id: 'b1',
  original_cbm: '2.5',
  corrected_cbm: null,
  status: 'submitted' as const,
  submitted_at: '2026-06-01T10:00:00Z',
}

function renderPage(role = 'nigeria_office_staff', routeState: object | null = { billing: BILLING_STUB }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[{ pathname: '/billing/b1', state: routeState ?? undefined }]}>
        <SessionContext.Provider value={makeCtx(role)}>
          <Routes>
            <Route path="/billing/:id" element={<BillingDetail />} />
          </Routes>
        </SessionContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { queryClient }
}

beforeEach(() => {
  vi.mocked(billingApi.list).mockReset()
  vi.mocked(billingApi.recordPayment).mockReset()
  vi.mocked(billingApi.cancel).mockReset()
  vi.mocked(disputeApi.acknowledge).mockReset()
  vi.mocked(disputeApi.resolve).mockReset()
  vi.mocked(paymentClaimApi.listForBilling).mockReset().mockResolvedValue([])
  vi.mocked(paymentClaimApi.confirm).mockReset()
  vi.mocked(paymentClaimApi.reject).mockReset()
})

describe('BillingDetail', () => {
  it('renders billing info from router state (no API fetch)', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('ACME001')).toBeInTheDocument())
    expect(screen.getByText('Unpaid')).toBeInTheDocument()
    // Payments table
    expect(screen.getByText('CASH001')).toBeInTheDocument()
    // No API call since state was provided
    expect(billingApi.list).not.toHaveBeenCalled()
  })

  it('falls back to API fetch when no router state', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [BILLING_STUB],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage('nigeria_office_staff', null)
    await waitFor(() => expect(billingApi.list).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('ACME001')).toBeInTheDocument())
  })

  it('shows Record payment button for nigeria on unpaid billing', async () => {
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Record payment' })).toBeInTheDocument())
  })

  it('hides Record payment for china_office_staff', async () => {
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('ACME001')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Record payment' })).not.toBeInTheDocument()
  })

  it('shows customer + invoice context and the outstanding balance in the record-payment modal', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Record payment' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Record payment' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Amara Nnamani')).toBeInTheDocument()
    expect(within(dialog).getByText('+2348090000001')).toBeInTheDocument()
    expect(within(dialog).getByText('ACM-INV-0001')).toBeInTheDocument()
    expect(within(dialog).getByText('Outstanding')).toBeInTheDocument()
    // Amount is pre-filled with the outstanding balance.
    expect(within(dialog).getByLabelText('Amount (₦)', { exact: false })).toHaveValue(174375)
  })

  it('scopes the carryover picker to the billing’s customer', async () => {
    vi.mocked(carryoverApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Apply carryover' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Apply carryover' }))
    await waitFor(() =>
      expect(carryoverApi.list).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'outstanding', customer_id: 'cust1' }),
      ),
    )
  })

  it('shows overpayment warning when entered amount exceeds outstanding', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Record payment' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Record payment' }))
    const dialog = screen.getByRole('dialog')
    const input = within(dialog).getByLabelText('Amount (₦)', { exact: false })
    await userEvent.type(input, '999999')
    await waitFor(() => expect(within(dialog).getByText(/overpayment will accrue/)).toBeInTheDocument())
  })

  it('submits record payment and reloads', async () => {
    vi.mocked(billingApi.recordPayment).mockResolvedValue({ new_payment_status: 'paid', amount_ngn: '174375' })
    vi.mocked(billingApi.list).mockResolvedValue({ data: [{ ...BILLING_STUB, payment_status: 'paid', total_paid_ngn: '174375.00', outstanding_ngn: '0.00' }], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Record payment' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Record payment' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Amount (₦)', { exact: false }), '174375')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm payment' }))
    await waitFor(() => expect(billingApi.recordPayment).toHaveBeenCalled())
  })

  it('shows acknowledge + resolve buttons for nigeria on submitted dispute', async () => {
    const billingWithDispute = { ...BILLING_STUB, _active_disputes: [DISPUTE_STUB] }
    renderPage('nigeria_office_staff', { billing: billingWithDispute })
    await waitFor(() => expect(screen.getByText('CBM dispute')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  })

  it('shows no dispute actions when dispute is terminal', async () => {
    const resolved = { ...DISPUTE_STUB, status: 'resolved_no_change' as const }
    const billingWithDispute = { ...BILLING_STUB, _active_disputes: [resolved] }
    renderPage('nigeria_office_staff', { billing: billingWithDispute })
    await waitFor(() => expect(screen.getByText('Resolved — no change')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
  })

  describe('cache invalidation after mutations (ground-truth fix: "i approved a payment, but it did not record the payment as paid, until i refreshed the page")', () => {
    function makeClaim(overrides = {}) {
      return {
        id: 'claim1',
        tenant_id: 't1',
        billing_id: 'b1',
        customer_id: 'cust1',
        amount_ngn: '174375.00',
        evidence_file_key: 't1/payment-claims/b1/receipt.jpg',
        evidence_file_name: 'receipt.jpg',
        customer_note: null,
        status: 'pending' as const,
        rejection_reason: null,
        reviewed_by: null,
        reviewed_at: null,
        payment_record_id: null,
        submitted_at: '2026-09-13T10:00:00Z',
        ...overrides,
      }
    }

    it('confirming a payment claim invalidates the billing query cache, not just local state', async () => {
      vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([makeClaim()])
      vi.mocked(paymentClaimApi.confirm).mockResolvedValue(makeClaim({ status: 'confirmed' }))
      vi.mocked(billingApi.list).mockResolvedValue({
        data: [{ ...BILLING_STUB, payment_status: 'paid', outstanding_ngn: '0.00' }],
        meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
      })
      const { queryClient } = renderPage()
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      const confirmBtn = await screen.findByRole('button', { name: 'Confirm' })
      await userEvent.click(confirmBtn)

      await waitFor(() => expect(paymentClaimApi.confirm).toHaveBeenCalledWith('claim1'))
      await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['billing'] }))
    })

    it('rejecting a payment claim also invalidates the billing query cache', async () => {
      vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([makeClaim()])
      vi.mocked(paymentClaimApi.reject).mockResolvedValue(makeClaim({ status: 'rejected', rejection_reason: 'no funds received' }))
      const { queryClient } = renderPage()
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      await userEvent.click(await screen.findByRole('button', { name: 'Reject' }))
      await userEvent.type(screen.getByPlaceholderText('Reason for rejecting'), 'no funds received')
      await userEvent.click(screen.getByRole('button', { name: 'Confirm reject' }))

      await waitFor(() => expect(paymentClaimApi.reject).toHaveBeenCalledWith('claim1', 'no funds received'))
      await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['billing'] }))
    })

    it('recording a payment invalidates the billing query cache so BillingList stops showing stale data', async () => {
      vi.mocked(billingApi.recordPayment).mockResolvedValue({ new_payment_status: 'paid', amount_ngn: '174375' })
      vi.mocked(billingApi.list).mockResolvedValue({
        data: [{ ...BILLING_STUB, payment_status: 'paid', outstanding_ngn: '0.00' }],
        meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
      })
      const { queryClient } = renderPage()
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      await userEvent.click(await screen.findByRole('button', { name: 'Record payment' }))
      const dialog = screen.getByRole('dialog')
      await userEvent.type(within(dialog).getByLabelText('Amount (₦)', { exact: false }), '174375')
      await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm payment' }))

      await waitFor(() => expect(billingApi.recordPayment).toHaveBeenCalled())
      await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['billing'] }))
    })
  })
})
