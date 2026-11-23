/**
 * Ground-truth gap found live: this page used to unconditionally claim
 * success and rely entirely on the gateway webhook — which can never reach
 * a local dev URL, and can be delayed/lost even in production. The customer
 * saw Paystack's own success page, clicked "View invoice", and found the
 * bill still unpaid with "Pay" still live. It now calls
 * billingApi.verifyPayment() with the reference Paystack appends to this
 * URL and reflects what actually happened.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { billingApi } from '../../api/billing'
import { ApiError } from '../../api/client'
import { withQuery } from '../../test/queryWrapper'
import { PaymentSuccess } from './PaymentSuccess'

vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return {
    ...original,
    // `get` feeds the invoice number into the breadcrumb (useInvoiceCrumb).
    billingApi: {
      ...original.billingApi,
      verifyPayment: vi.fn(),
      get: vi.fn(async () => ({ invoice_number: 'ACM-INV-0001' })),
    },
  }
})

function renderPage(search = '?reference=b1.abc123') {
  return render(
    withQuery(
      <MemoryRouter initialEntries={[`/my-billing/b1/payment-success${search}`]}>
        <Routes>
          <Route path="/my-billing/:id/payment-success" element={<PaymentSuccess />} />
          <Route path="/my-billing/:id" element={<div>billing detail page</div>} />
          <Route path="/my-billing" element={<div>billing list page</div>} />
        </Routes>
      </MemoryRouter>,
    ),
  )
}

describe('PaymentSuccess', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows a confirming state, then verifies the payment with the reference from the URL', async () => {
    vi.mocked(billingApi.verifyPayment).mockResolvedValue({
      gateway_status: 'success',
      new_payment_status: 'paid',
    })
    renderPage()

    expect(screen.getByText('Confirming your payment…')).toBeInTheDocument()
    expect(await screen.findByText('Payment successful!')).toBeInTheDocument()
    expect(billingApi.verifyPayment).toHaveBeenCalledWith('b1', 'b1.abc123')
  })

  it('reads trxref when reference is absent (Paystack sends both, sometimes only one)', async () => {
    vi.mocked(billingApi.verifyPayment).mockResolvedValue({ gateway_status: 'success' })
    renderPage('?trxref=b1.xyz789')

    await screen.findByText('Payment successful!')
    expect(billingApi.verifyPayment).toHaveBeenCalledWith('b1', 'b1.xyz789')
  })

  it('shows a pending state when Paystack has not confirmed success', async () => {
    vi.mocked(billingApi.verifyPayment).mockResolvedValue({ gateway_status: 'abandoned' })
    renderPage()

    expect(await screen.findByText('Payment not yet confirmed')).toBeInTheDocument()
  })

  it('shows a non-scary error state when verification itself fails', async () => {
    vi.mocked(billingApi.verifyPayment).mockRejectedValue(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Gateway unreachable',
          status: 502,
          detail: 'Gateway unreachable',
          error_code: 'EXTERNAL_SERVICE_ERROR',
        },
        'req-1',
      ),
    )
    renderPage()

    expect(
      await screen.findByText("Couldn't confirm your payment automatically"),
    ).toBeInTheDocument()
    expect(screen.getByText(/Gateway unreachable/)).toBeInTheDocument()
  })

  it('shows an error state with no API call when there is no reference at all', async () => {
    renderPage('')

    expect(
      await screen.findByText("Couldn't confirm your payment automatically"),
    ).toBeInTheDocument()
    expect(billingApi.verifyPayment).not.toHaveBeenCalled()
  })

  it('"View invoice" navigates to the billing detail page', async () => {
    vi.mocked(billingApi.verifyPayment).mockResolvedValue({ gateway_status: 'success' })
    renderPage()
    await screen.findByText('Payment successful!')

    await userEvent.click(screen.getByRole('button', { name: 'View invoice' }))

    expect(await screen.findByText('billing detail page')).toBeInTheDocument()
  })
})
