import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { billingApi, type UnbilledCustomer } from '../api/billing'
import { ApiError } from '../api/client'
import { withQuery } from '../test/queryWrapper'
import { UnbilledQueue } from './UnbilledQueue'

vi.mock('../api/billing', () => ({
  billingApi: { unbilled: vi.fn(), generateForContainer: vi.fn() },
}))

function row(overrides: Partial<UnbilledCustomer>): UnbilledCustomer {
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

function renderQueue() {
  return render(withQuery(<MemoryRouter><UnbilledQueue /></MemoryRouter>))
}

describe('UnbilledQueue', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders nothing when every customer has been invoiced', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([])
    const { container } = renderQueue()
    await waitFor(() => expect(billingApi.unbilled).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('groups customers under their container', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([
      row({}),
      row({ customer_id: 'c2', customer_name: 'Bob' }),
      row({ container_id: 'k2', container_number: 'ACME002', customer_id: 'c3', customer_name: 'Chi' }),
    ])
    renderQueue()

    expect(await screen.findByText('Customers not invoiced')).toBeInTheDocument()
    expect(screen.getByText('ACME001')).toBeInTheDocument()
    expect(screen.getByText('Alice, Bob')).toBeInTheDocument()
    expect(screen.getByText('ACME002')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Generate invoices' })).toHaveLength(2)
  })

  it('abbreviates a long customer list', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue(
      ['A', 'B', 'C', 'D', 'E'].map((n, i) => row({ customer_id: `c${i}`, customer_name: n })),
    )
    renderQueue()
    expect(await screen.findByText('A, B, C +2 more')).toBeInTheDocument()
  })

  it('generates invoices for just that container', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([row({})])
    vi.mocked(billingApi.generateForContainer).mockResolvedValue({ container_id: 'k1', results: [] })
    renderQueue()

    await userEvent.click(await screen.findByRole('button', { name: 'Generate invoices' }))

    expect(billingApi.generateForContainer).toHaveBeenCalledWith('k1')
  })

  it('shows the server message when generation is refused', async () => {
    vi.mocked(billingApi.unbilled).mockResolvedValue([row({})])
    vi.mocked(billingApi.generateForContainer).mockRejectedValue(
      new ApiError(
        { type: 'x', title: 'x', status: 422, detail: 'Invoices can only be generated once the container has cleared customs.', error_code: 'BUSINESS_RULE_VIOLATION' },
        null,
      ),
    )
    renderQueue()

    await userEvent.click(await screen.findByRole('button', { name: 'Generate invoices' }))

    expect(await screen.findByText(/once the container has cleared customs/)).toBeInTheDocument()
  })
})
