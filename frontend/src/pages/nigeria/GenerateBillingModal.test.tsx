import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { billingApi, type InvoiceResult, type UnbilledCustomer } from '../../api/billing'
import { ApiError } from '../../api/client'
import { withQuery } from '../../test/queryWrapper'
import { GenerateBillingModal } from './GenerateBillingModal'

vi.mock('../../api/billing', () => ({
  billingApi: { unbilled: vi.fn(), generateForContainer: vi.fn() },
}))

function unbilled(overrides: Partial<UnbilledCustomer>): UnbilledCustomer {
  return {
    container_id: 'k1',
    container_number: 'ACME001',
    container_status: 'cleared',
    customer_id: 'c1',
    customer_name: 'Alice',
    total_cbm: '2.000',
    ...overrides,
  }
}

function result(overrides: Partial<InvoiceResult>): InvoiceResult {
  return {
    customer_id: 'c1',
    customer_name: 'Alice',
    status: 'created',
    billing_id: 'b1',
    invoice_number: 'INV-1',
    reason: null,
    detail: null,
    ...overrides,
  }
}

function apiError(status: number, detail: string): ApiError {
  return new ApiError({ type: 'x', title: 'x', status, detail, error_code: 'BUSINESS_RULE_VIOLATION' }, null)
}

const TWO_CONTAINERS = [
  unbilled({}),
  unbilled({ customer_id: 'c2', customer_name: 'Bob', total_cbm: '1.500' }),
  unbilled({ container_id: 'k2', container_number: 'ACME002', customer_id: 'c3', customer_name: 'Chi', total_cbm: '4.000' }),
]

function renderModal(onClose = vi.fn()) {
  render(withQuery(<GenerateBillingModal onClose={onClose} />))
  return onClose
}

describe('GenerateBillingModal', () => {
  beforeEach(() => vi.clearAllMocks())

  it('says so when every cleared container is already fully invoiced', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([])
    renderModal()

    expect(await screen.findByText('Nothing to invoice')).toBeInTheDocument()
    expect(screen.queryByLabelText('Container')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate invoices' })).toBeDisabled()
  })

  it('selects the only candidate container and lists who will be invoiced', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([unbilled({}), unbilled({ customer_id: 'c2', customer_name: 'Bob' })])
    renderModal()

    expect(await screen.findByLabelText('Container')).toHaveDisplayValue(/ACME001/)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate invoices' })).toBeEnabled()
  })

  it('makes the user choose when there are several containers', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue(TWO_CONTAINERS)
    renderModal()

    const picker = await screen.findByLabelText('Container')
    expect(picker).toHaveDisplayValue('Select a container…')
    expect(screen.getByRole('button', { name: 'Generate invoices' })).toBeDisabled()
    expect(screen.getByRole('option', { name: /ACME001 — 2 customers · 3\.500 CBM/ })).toBeInTheDocument()

    await userEvent.selectOptions(picker, 'k2')

    expect(screen.getByText('Chi')).toBeInTheDocument()
    expect(screen.queryByText('Alice')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate invoices' })).toBeEnabled()
  })

  it('invoices the chosen container and reports who was invoiced', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue(TWO_CONTAINERS)
    vi.mocked(billingApi.generateForContainer).mockResolvedValue({
      container_id: 'k2',
      results: [result({ customer_id: 'c3', customer_name: 'Chi' })],
    })
    const onClose = renderModal()

    await userEvent.selectOptions(await screen.findByLabelText('Container'), 'k2')
    await userEvent.click(screen.getByRole('button', { name: 'Generate invoices' }))

    await waitFor(() => expect(billingApi.generateForContainer).toHaveBeenCalledWith('k2'))
    expect(await screen.findByText('1 customer invoiced.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('shows a customer who still could not be invoiced, with the reason', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([unbilled({})])
    vi.mocked(billingApi.generateForContainer).mockResolvedValue({
      container_id: 'k1',
      results: [
        result({ customer_id: 'c1', customer_name: 'Alice' }),
        result({ customer_id: 'c2', customer_name: 'Bob', status: 'skipped', billing_id: null, invoice_number: null, reason: 'RATE_CONFIG_MISSING' }),
      ],
    })
    renderModal()

    await userEvent.click(await screen.findByRole('button', { name: 'Generate invoices' }))

    expect(await screen.findByText('1 customer not invoiced')).toBeInTheDocument()
    expect(screen.getByText(/CBM rate or dollar rate is not set/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate missing invoices' })).toBeInTheDocument()
  })

  it('keeps the picker open and shows the error when generation fails', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([unbilled({})])
    vi.mocked(billingApi.generateForContainer).mockRejectedValue(
      apiError(422, 'Container is not cleared.'),
    )
    renderModal()

    await userEvent.click(await screen.findByRole('button', { name: 'Generate invoices' }))

    expect(await screen.findByText('Container is not cleared.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate invoices' })).toBeEnabled()
  })

  it('shows an error when the container list cannot be loaded', async () => {
    vi.mocked(billingApi.unbilled).mockRejectedValue(apiError(500, 'Server exploded.'))
    renderModal()

    expect(await screen.findByText("Couldn't load containers")).toBeInTheDocument()
    expect(screen.getByText('Something went wrong on our side. Try again; if it keeps happening, contact support.')).toBeInTheDocument()
  })
})
