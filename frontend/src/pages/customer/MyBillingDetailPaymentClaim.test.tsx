/**
 * Ground-truth gap found live, reported directly by the user: after
 * submitting a manual-transfer payment claim, "Pay online" stayed fully
 * active and the page gave no indication a payment was already in flight —
 * a customer could click it and pay a second time. This regression-guards
 * the fix: a pending claim replaces the payment options with an "awaiting
 * confirmation" banner; a rejected claim (no pending one) surfaces the
 * reason and restores the normal payment options.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { paymentClaimApi } from '../../api/billing'
import { configApi } from '../../api/tenantManagement'
import { MyBillingDetail } from './MyBillingDetail'

vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return {
    ...original,
    paymentClaimApi: { ...original.paymentClaimApi, listForBilling: vi.fn() },
  }
})
vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, configApi: { ...original.configApi, getConfig: vi.fn() } }
})

const BILLING = {
  id: 'b1', invoice_number: 'BL-1', customer_id: 'c1', customer_name: null,
  container_id: 'cont1', container_number: 'MSCU1234567',
  total_cbm: '0.56', cbm_rate_usd: '45', dollar_rate: '1550',
  subtotal_usd: '25.2', subtotal_ngn: '39060', misc_fees: [], misc_fees_ngn: 0,
  adjustments_ngn: '0', carryover_ngn: 0, storage_fees_ngn: 0,
  total_due_ngn: '100008', total_paid_ngn: '49352', outstanding_ngn: '50656',
  payment_status: 'partially_paid', released_with_outstanding: false,
  billed_at: null, payments: [], carryovers: [], _active_disputes: [],
}

function claim(status: 'pending' | 'confirmed' | 'rejected', overrides: Record<string, unknown> = {}) {
  return {
    id: 'claim1', tenant_id: 't1', billing_id: 'b1', customer_id: 'c1',
    amount_ngn: '50656', evidence_file_key: 'k', evidence_file_name: 'receipt.jpg',
    customer_note: null, status, rejection_reason: null, reviewed_by: null,
    reviewed_at: null, payment_record_id: null, submitted_at: '2026-09-07T10:00:00Z',
    ...overrides,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[{ pathname: '/my-billing/b1', state: { billing: BILLING } }]}>
        <Routes>
          <Route path="/my-billing/:id" element={<MyBillingDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { queryClient }
}

describe('MyBillingDetail — payment options reflect an in-flight claim', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.getConfig).mockResolvedValue({ bank_transfer_config: null } as never)
  })

  it('hides Pay online and shows an awaiting-confirmation banner while a claim is pending', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([claim('pending')] as never)
    renderPage()

    expect(await screen.findByText('Payment submitted — awaiting confirmation')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /pay .* online/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /show bank details/i })).toBeNull()
  })

  it('shows the rejection reason and restores normal payment options when nothing is pending', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([
      claim('rejected', { rejection_reason: "Amount doesn't match the invoice" }),
    ] as never)
    renderPage()

    expect(await screen.findByText('Your last payment claim was rejected')).toBeInTheDocument()
    expect(screen.getByText(/Amount doesn't match the invoice/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /pay .* online/i })).toBeInTheDocument()
    // A prior claim (even rejected) auto-expands bank details rather than
    // requiring "Show bank details" again — the resubmit form is right there.
    expect(screen.getByRole('button', { name: /i've made this payment/i })).toBeInTheDocument()
  })

  it('shows normal payment options when there are no claims at all', async () => {
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([] as never)
    renderPage()

    expect(await screen.findByRole('button', { name: /pay .* online/i })).toBeInTheDocument()
    expect(screen.queryByText('Payment submitted — awaiting confirmation')).toBeNull()
    expect(screen.queryByText('Your last payment claim was rejected')).toBeNull()
  })
})
