/**
 * Staff-side review of customer-submitted "I've made this payment" claims.
 * Answers directly the question of how a manual bank transfer actually gets
 * confirmed: nigeria_office_staff/tenant_admin see a "Payment claims" table
 * on the billing detail page, can view the uploaded evidence, and
 * Confirm/Reject a pending one.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { billingApi, paymentClaimApi } from '../../api/billing'
import { BillingDetail } from './BillingDetail'

vi.mock('../../api/billing', () => ({
  billingApi: { list: vi.fn(), get: vi.fn(), listForCustomer: vi.fn(), recordPayment: vi.fn(), cancel: vi.fn(), applyCarryover: vi.fn() },
  disputeApi: { list: vi.fn(), acknowledge: vi.fn(), resolve: vi.fn(), reject: vi.fn() },
  carryoverApi: { list: vi.fn(), exempt: vi.fn() },
  paymentClaimApi: { listForBilling: vi.fn(), confirm: vi.fn(), reject: vi.fn(), getEvidenceUrl: vi.fn() },
}))

function makeSession(role = 'nigeria_office_staff'): Session {
  return {
    tenantId: 't1', userId: 'u1', name: null,
    role: role as Session['role'], roles: [role as Session['role']],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null, readOnly: false,
    expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
}
function makeCtx(role = 'nigeria_office_staff'): SessionContextValue {
  return {
    session: makeSession(role), status: 'authenticated',
    login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(),
    startImpersonation: vi.fn(), exitImpersonation: vi.fn(),
  }
}

const BILLING_STUB = {
  id: 'b1', container_id: 'c1', container_number: 'ACME001',
  total_cbm: '2.500000', cbm_rate_usd: '45.0000', dollar_rate: '1550.0000',
  subtotal_usd: '112.50', subtotal_ngn: '174375.00', misc_fees: [], misc_fees_ngn: 0,
  adjustments_ngn: '0', carryover_ngn: 0, storage_fees_ngn: 0,
  total_due_ngn: '174375.00', total_paid_ngn: '0', outstanding_ngn: '174375.00',
  payment_status: 'unpaid' as const, released_with_outstanding: false, billed_at: null,
  payments: [], carryovers: [], _active_disputes: [],
}

const CLAIM = {
  id: 'claim1', tenant_id: 't1', billing_id: 'b1', customer_id: 'cust1',
  amount_ngn: '174375.00', evidence_file_key: 't1/payment-claims/b1/receipt.jpg',
  evidence_file_name: 'receipt.jpg', customer_note: null,
  status: 'pending' as const, rejection_reason: null, reviewed_by: null,
  reviewed_at: null, payment_record_id: null, submitted_at: '2026-09-07T10:00:00Z',
}

function renderPage(role = 'nigeria_office_staff') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[{ pathname: '/billing/b1', state: { billing: BILLING_STUB } }]}>
        <SessionContext.Provider value={makeCtx(role)}>
          <Routes>
            <Route path="/billing/:id" element={<BillingDetail />} />
          </Routes>
        </SessionContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BillingDetail — staff payment-claim review', () => {
  it('shows a pending claim with Confirm/Reject for nigeria_office_staff', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([CLAIM])
    renderPage('nigeria_office_staff')

    expect(await screen.findByText('Payment claims')).toBeInTheDocument()
    expect(screen.getByText('receipt.jpg')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^confirm$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^reject$/i })).toBeInTheDocument()
  })

  it('confirming calls the confirm endpoint and refreshes the claim', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([CLAIM])
    vi.mocked(paymentClaimApi.confirm).mockResolvedValue({ ...CLAIM, status: 'confirmed' })
    vi.mocked(billingApi.get).mockResolvedValue({ ...BILLING_STUB, payment_status: 'paid', total_paid_ngn: '174375.00', outstanding_ngn: '0' })
    renderPage('nigeria_office_staff')

    await screen.findByText('Payment claims')
    await userEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^confirm payment$/i }))

    await waitFor(() => expect(paymentClaimApi.confirm).toHaveBeenCalledWith('claim1'))
  })

  it('rejecting requires a reason before it can be submitted', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([CLAIM])
    vi.mocked(paymentClaimApi.reject).mockResolvedValue({ ...CLAIM, status: 'rejected', rejection_reason: 'no match' })
    renderPage('nigeria_office_staff')

    await screen.findByText('Payment claims')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))

    const confirmRejectBtn = screen.getByRole('button', { name: /confirm reject/i })
    expect(confirmRejectBtn).toBeDisabled()

    await userEvent.type(screen.getByPlaceholderText(/reason for rejecting/i), 'Amount does not match')
    expect(confirmRejectBtn).toBeEnabled()
    await userEvent.click(confirmRejectBtn)

    await waitFor(() => expect(paymentClaimApi.reject).toHaveBeenCalledWith('claim1', 'Amount does not match'))
  })

  it('viewing evidence opens the presigned URL', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([CLAIM])
    vi.mocked(paymentClaimApi.getEvidenceUrl).mockResolvedValue({ url: 'https://s3.example.com/signed-receipt.jpg' })
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    renderPage('nigeria_office_staff')

    await screen.findByText('Payment claims')
    await userEvent.click(screen.getByRole('button', { name: /receipt\.jpg/i }))

    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('https://s3.example.com/signed-receipt.jpg', '_blank', 'noopener'))
  })

  it('renders no payment-claims section when there are none', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([])
    renderPage('nigeria_office_staff')

    await waitFor(() => expect(screen.getByText('ACME001')).toBeInTheDocument())
    expect(screen.queryByText('Payment claims')).toBeNull()
  })
})
