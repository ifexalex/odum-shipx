/**
 * The customer's invoice list (audit OPS-03: money-moving pages are tested first).
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { billingApi, type Billing } from '../../api/billing'
import { withQuery } from '../../test/queryWrapper'
import { MyBilling } from './MyBilling'

vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return { ...original, billingApi: { ...original.billingApi, list: vi.fn() } }
})

function invoice(overrides: Partial<Billing>): Billing {
  return {
    id: 'b1',
    container_id: 'c1',
    container_number: 'ACME001',
    total_due_ngn: '174375.00',
    total_paid_ngn: '74375.00',
    outstanding_ngn: '100000.00',
    payment_status: 'partially_paid',
    ...overrides,
  } as Billing
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter initialEntries={['/my-billing']}>
        <Routes>
          <Route path="/my-billing" element={<MyBilling />} />
          <Route path="/my-billing/:id" element={<div>Invoice detail</div>} />
        </Routes>
      </MemoryRouter>,
    ),
  )
}

beforeEach(() => vi.clearAllMocks())

describe('MyBilling', () => {
  it('shows each invoice with what is due, paid and still owed', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [invoice({}), invoice({ id: 'b2', container_number: 'ACME002', total_due_ngn: '0.00', total_paid_ngn: '0.00', outstanding_ngn: '0.00', payment_status: 'paid' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    } as Awaited<ReturnType<typeof billingApi.list>>)
    renderPage()
    expect(await screen.findByText('ACME001')).toBeInTheDocument()
    expect(screen.getByText('Partly paid')).toBeInTheDocument()
    expect(screen.getByText('₦100,000 outstanding')).toBeInTheDocument()
    // An invoice fully covered by credit (BE-07) is paid, with nothing outstanding to show.
    expect(screen.getByText('Paid')).toBeInTheDocument()
    expect(screen.getAllByText(/outstanding$/)).toHaveLength(1)
  })

  it('opens an invoice', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [invoice({})],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as Awaited<ReturnType<typeof billingApi.list>>)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /ACME001/ }))
    expect(screen.getByText('Invoice detail')).toBeInTheDocument()
  })

  it('says so when there are no invoices', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    } as Awaited<ReturnType<typeof billingApi.list>>)
    renderPage()
    expect(await screen.findByText("You're all caught up!")).toBeInTheDocument()
  })

  it('asks the server for the list without a customer filter: the server scopes it to the caller', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } } as Awaited<ReturnType<typeof billingApi.list>>)
    renderPage()
    await screen.findByText("You're all caught up!")
    expect(billingApi.list).toHaveBeenCalledWith({ cursor: undefined })
  })
})
