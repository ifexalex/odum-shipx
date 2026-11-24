import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { billingApi, type InvoiceResult } from '../../api/billing'
import { ApiError } from '../../api/client'
import { InvoiceOutcomeBanner } from './InvoiceOutcomeBanner'

vi.mock('../../api/billing', () => ({
  billingApi: { generateForContainer: vi.fn() },
}))

function row(overrides: Partial<InvoiceResult>): InvoiceResult {
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

describe('InvoiceOutcomeBanner', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders nothing when there are no results', () => {
    const { container } = render(
      <InvoiceOutcomeBanner containerId="k1" results={[]} canGenerate onResults={() => undefined} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('confirms when everyone was invoiced', () => {
    render(
      <InvoiceOutcomeBanner
        containerId="k1"
        results={[row({}), row({ customer_id: 'c2', customer_name: 'Bob' })]}
        canGenerate
        onResults={() => undefined}
      />,
    )
    expect(screen.getByText('Invoices issued')).toBeInTheDocument()
    expect(screen.getByText('2 customers invoiced.')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('names each customer who was not invoiced, with the reason', () => {
    render(
      <InvoiceOutcomeBanner
        containerId="k1"
        results={[
          row({}),
          row({ customer_id: 'c2', customer_name: 'Bob', status: 'skipped', reason: 'RATE_CONFIG_MISSING' }),
          row({ customer_id: 'c3', customer_name: 'Chi', status: 'failed', reason: 'GENERATION_ERROR' }),
        ]}
        canGenerate
        onResults={() => undefined}
      />,
    )
    expect(screen.getByText('2 customers not invoiced')).toBeInTheDocument()
    expect(screen.getByText(/CBM rate or dollar rate is not set/)).toBeInTheDocument()
    expect(screen.getByText(/the invoice could not be created/)).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
  })

  it('retries and hands the new results to the parent', async () => {
    const onResults = vi.fn()
    const fixed = [row({}), row({ customer_id: 'c2', customer_name: 'Bob', status: 'created' })]
    vi.mocked(billingApi.generateForContainer).mockResolvedValue({ container_id: 'k1', results: fixed })

    render(
      <InvoiceOutcomeBanner
        containerId="k1"
        results={[row({ customer_id: 'c2', customer_name: 'Bob', status: 'failed', reason: 'GENERATION_ERROR' })]}
        canGenerate
        onResults={onResults}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Generate missing invoices' }))

    expect(billingApi.generateForContainer).toHaveBeenCalledWith('k1')
    await waitFor(() => expect(onResults).toHaveBeenCalledWith(fixed))
  })

  it('shows the server message when the retry is refused', async () => {
    vi.mocked(billingApi.generateForContainer).mockRejectedValue(
      new ApiError(
        { type: 'x', title: 'x', status: 422, detail: 'Invoices can only be generated once the container has cleared customs.', error_code: 'BUSINESS_RULE_VIOLATION' },
        null,
      ),
    )
    render(
      <InvoiceOutcomeBanner
        containerId="k1"
        results={[row({ status: 'skipped', reason: 'NO_CBM' })]}
        canGenerate
        onResults={() => undefined}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Generate missing invoices' }))
    expect(await screen.findByText(/once the container has cleared customs/)).toBeInTheDocument()
  })

  it('does not offer the retry to a role that cannot run it', () => {
    render(
      <InvoiceOutcomeBanner
        containerId="k1"
        results={[row({ status: 'skipped', reason: 'NO_CBM' })]}
        canGenerate={false}
        onResults={() => undefined}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Generate missing invoices' })).not.toBeInTheDocument()
    expect(screen.getByText(/Ask your Nigeria office or admin/)).toBeInTheDocument()
  })
})
