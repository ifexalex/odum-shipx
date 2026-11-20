/**
 * B12 — customer pay-online: the Pay button initializes a Paystack checkout
 * and redirects to the hosted authorization_url; failures surface inline and
 * never navigate away.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { billingApi, paymentClaimApi } from '../../api/billing'
import { configApi } from '../../api/tenantManagement'
import { MyBillingDetail } from './MyBillingDetail'

vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return {
    ...original,
    billingApi: { ...original.billingApi, get: vi.fn(), initializePayment: vi.fn(), export: vi.fn() },
    disputeApi: { ...original.disputeApi, file: vi.fn() },
    paymentClaimApi: { ...original.paymentClaimApi, listForBilling: vi.fn(), submit: vi.fn() },
  }
})

// The page reads bank-transfer details and its own payment claims through
// TanStack Query (master plan 7.150). Both are stubbed so no real request is
// attempted and the panel starts closed.
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

describe('MyBillingDetail — pay online (B12)', () => {
  const assignSpy = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([])
    vi.mocked(configApi.getConfig).mockResolvedValue({} as never)
    // window.location.assign is not writable directly in jsdom
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign: assignSpy, origin: 'https://acme.shipx.co' },
      writable: true,
    })
  })

  it('initializes a checkout with the payment-success callback and redirects', async () => {
    vi.mocked(billingApi.initializePayment).mockResolvedValue({
      authorization_url: 'https://checkout.paystack.com/abc123',
      reference: 'b1:deadbeef00',
      access_code: 'abc',
      amount_ngn: '50656',
    })
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /pay ₦50,656 online/i }))

    await waitFor(() => {
      expect(billingApi.initializePayment).toHaveBeenCalledWith(
        'b1',
        'https://acme.shipx.co/my-billing/b1/payment-success',
      )
    })
    expect(assignSpy).toHaveBeenCalledWith('https://checkout.paystack.com/abc123')
  })

  it('surfaces initialize failures inline without navigating', async () => {
    vi.mocked(billingApi.initializePayment).mockRejectedValue(
      new ApiError(
        {
          type: 'about:blank', title: 'Business Rule Violation', status: 422,
          detail: 'Add an email address to your profile to pay online — the payment gateway requires one.',
          error_code: 'BUSINESS_RULE_VIOLATION',
        },
        null,
      ),
    )
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /pay ₦50,656 online/i }))

    expect(await screen.findByText(/add an email address to your profile/i)).toBeInTheDocument()
    expect(assignSpy).not.toHaveBeenCalled()
  })
})

// Ground-truth fix (2026-07-19) — the customer billing page had no way to
// actually download an invoice; GET /v1/billing/{id}/export was staff-only
// and this button didn't exist at all.
describe('MyBillingDetail — download invoice', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(paymentClaimApi.listForBilling).mockResolvedValue([])
    vi.mocked(configApi.getConfig).mockResolvedValue({} as never)
  })

  it('downloads the invoice as a pdf', async () => {
    vi.mocked(billingApi.export).mockResolvedValue(undefined)
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /download invoice/i }))

    await waitFor(() => expect(billingApi.export).toHaveBeenCalledWith('b1', 'pdf'))
  })

  it('surfaces export failures inline', async () => {
    vi.mocked(billingApi.export).mockRejectedValue(
      new ApiError(
        { type: 'about:blank', title: 'Not Found', status: 404, detail: 'Invoice not found.', error_code: 'RESOURCE_NOT_FOUND' },
        null,
      ),
    )
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /download invoice/i }))

    expect(await screen.findByText(/couldn't find that/i)).toBeInTheDocument()
  })
})
