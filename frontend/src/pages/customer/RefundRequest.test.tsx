/**
 * The customer's refund request (audit OPS-03: money-moving pages are tested first).
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { JSX } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { refundsApi } from '../../api/refunds'
import { withQuery } from '../../test/queryWrapper'
import { RefundRequest } from './RefundRequest'

vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  // `get` feeds the invoice number into the breadcrumb (useInvoiceCrumb).
  return {
    ...original,
    billingApi: {
      ...original.billingApi,
      get: vi.fn(async () => ({ invoice_number: 'ACM-INV-0001' })),
    },
  }
})

vi.mock('../../api/refunds', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/refunds')>()
  return { ...original, refundsApi: { ...original.refundsApi, create: vi.fn() } }
})

function InvoicePage(): JSX.Element {
  const { state } = useLocation()
  return (
    <div>
      Invoice page{' '}
      {(state as { refundFiled?: boolean } | null)?.refundFiled ? '(refund filed)' : ''}
    </div>
  )
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter initialEntries={['/my-billing/b1/refund-request']}>
        <Routes>
          <Route path="/my-billing/:id/refund-request" element={<RefundRequest />} />
          <Route path="/my-billing/:id" element={<InvoicePage />} />
        </Routes>
      </MemoryRouter>,
    ),
  )
}

beforeEach(() => vi.clearAllMocks())

describe('RefundRequest', () => {
  it('cannot be sent without a positive amount', async () => {
    renderPage()
    const submit = screen.getByRole('button', { name: 'Submit request' })
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Amount requested/), '0')
    expect(submit).toBeDisabled()
  })

  it('sends the request against this invoice, with the chosen payout, and returns to the invoice', async () => {
    vi.mocked(refundsApi.create).mockResolvedValue(
      {} as Awaited<ReturnType<typeof refundsApi.create>>,
    )
    renderPage()
    await userEvent.type(screen.getByLabelText(/Amount requested/), '25000')
    await userEvent.type(screen.getByLabelText(/Reason for refund/), 'Paid twice')
    await userEvent.click(screen.getByLabelText(/Credit on next shipment/))
    await userEvent.click(screen.getByRole('button', { name: 'Submit request' }))

    const [body, idempotencyKey] = vi.mocked(refundsApi.create).mock.calls[0]!
    expect(body).toEqual({
      customer_id: '',
      billing_id: 'b1',
      refund_type: 'overpayment',
      amount_requested_ngn: '25000',
      customer_choice: 'credit_next_shipment',
      notes: 'Paid twice',
    })
    expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)
    expect(await screen.findByText('Invoice page (refund filed)')).toBeInTheDocument()
  })

  it('uses the same idempotency key when the customer tries again after a failure', async () => {
    vi.mocked(refundsApi.create)
      .mockRejectedValueOnce(
        new ApiError(
          {
            type: 'about:blank',
            title: 'x',
            status: 503,
            detail: 'Try again shortly.',
            error_code: 'SERVICE_UNAVAILABLE',
          },
          null,
        ),
      )
      .mockResolvedValueOnce({} as Awaited<ReturnType<typeof refundsApi.create>>)
    renderPage()
    await userEvent.type(screen.getByLabelText(/Amount requested/), '5000')
    await userEvent.click(screen.getByRole('button', { name: 'Submit request' }))
    expect(await screen.findByText('Try again shortly.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Submit request' }))

    const keys = vi.mocked(refundsApi.create).mock.calls.map((call) => call[1])
    expect(keys).toHaveLength(2)
    expect(keys[0]).toBe(keys[1]) // a retry must not file a second refund
  })

  it('says a credit only covers what the next invoice needs and keeps the rest', () => {
    renderPage()
    expect(screen.getByText(/anything left over stays as credit/)).toBeInTheDocument()
  })
})
