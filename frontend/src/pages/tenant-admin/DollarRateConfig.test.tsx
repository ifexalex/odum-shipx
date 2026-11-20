/**
 * Dollar rate (2026-09-19) — the rate is no longer a number an admin types
 * in. The base rate now tracks Bybit's live P2P black-market USD/NGN order
 * book (shared/fx_rate.py); a tenant_admin only sets a markup on top of it
 * (percentage or a flat ₦-per-$1 amount). This page reflects that: it shows
 * base rate / markup / effective rate, and the update form edits the markup.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { configApi, type DollarRateConfig as DollarRateConfigShape } from '../../api/tenantManagement'
import { DollarRateConfig } from './DollarRateConfig'
import { withQuery } from '../../test/queryWrapper'

function renderPage(): ReturnType<typeof render> {
  return render(withQuery(
    <MemoryRouter>
      <DollarRateConfig />
    </MemoryRouter>,
  ))
}

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    configApi: {
      ...original.configApi,
      getDollarRate: vi.fn(),
      updateDollarRate: vi.fn(),
      rateHistory: vi.fn(),
    },
  }
})

function rate(overrides: Partial<DollarRateConfigShape> = {}): DollarRateConfigShape {
  return {
    rate: 1588.2,
    base_rate: 1573.2,
    markup_type: 'flat',
    markup_value: 15,
    source: 'bybit_p2p',
    rate_source: 'live',
    fetched_at: new Date().toISOString(),
    currency_pair: 'USD_NGN',
    effective_from: '2026-09-18T09:00:00Z',
    ...overrides,
  }
}

describe('DollarRateConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.rateHistory).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
  })

  it('shows the base rate, markup, and effective rate', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate())
    renderPage()

    expect(await screen.findByText(/₦1,573.20 per \$1/)).toBeInTheDocument()
    expect(screen.getByText('₦15 per $1')).toBeInTheDocument()
    expect(screen.getByText('₦1,588.20 per $1 USD')).toBeInTheDocument()
  })

  it('says plainly when the feed is down and the last known rate is in use (audit BE-11)', async () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 3600 * 1000).toISOString()
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate({ rate_source: 'last_known', fetched_at: twoDaysAgo }))
    renderPage()

    expect(await screen.findByText(/last known rate, fetched/)).toBeInTheDocument()
    expect(screen.getByText(/invoices use the last known rate shown here/)).toBeInTheDocument()
  })

  it('never calls the built-in default "updated just now" (audit BE-11)', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate({ rate_source: 'hardcoded', fetched_at: null }))
    renderPage()

    expect(await screen.findByText(/built-in default, never fetched/)).toBeInTheDocument()
    expect(screen.queryByText(/updated/)).not.toBeInTheDocument()
    expect(screen.getByText(/Invoices are not issued until a market rate is available/)).toBeInTheDocument()
  })

  it('shows no warning for a live rate', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate())
    renderPage()

    expect(await screen.findByText(/updated/)).toBeInTheDocument()
    expect(screen.queryByText(/last known|built-in default/)).not.toBeInTheDocument()
  })

  it('formats a percentage markup distinctly from a flat one', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate({ markup_type: 'percentage', markup_value: 2.5 }))
    renderPage()

    expect(await screen.findByText('2.5%')).toBeInTheDocument()
  })

  it('pre-fills the form with the current markup type and value', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate({ markup_type: 'percentage', markup_value: 3 }))
    renderPage()
    await screen.findByText('3%')

    expect(screen.getByRole('button', { name: 'Percentage' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('e.g. 2')).toHaveValue(3)
  })

  it('switching to Flat changes the input label and placeholder', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate({ markup_type: 'percentage', markup_value: 2 }))
    renderPage()
    await screen.findByText('2%')

    await userEvent.click(screen.getByRole('button', { name: 'Flat ₦ per $1' }))

    expect(screen.getByText('Markup (₦ per $1)')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('e.g. 15')).toBeInTheDocument()
  })

  it('submits the markup update and refreshes the displayed rate', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate({ markup_type: 'flat', markup_value: 15 }))
    vi.mocked(configApi.updateDollarRate).mockResolvedValue(rate({ markup_type: 'flat', markup_value: 20, rate: 1593.2 }))
    renderPage()
    await screen.findByText('₦15 per $1')

    const input = screen.getByPlaceholderText('e.g. 15')
    await userEvent.clear(input)
    await userEvent.type(input, '20')
    await userEvent.click(screen.getByRole('button', { name: 'Update markup' }))

    await waitFor(() => expect(configApi.updateDollarRate).toHaveBeenCalledWith({ markup_type: 'flat', markup_value: 20 }))
    expect(await screen.findByText('Dollar rate markup updated')).toBeInTheDocument()
    expect(screen.getByText('₦20 per $1')).toBeInTheDocument()
  })

  it('disables Update markup when the value is cleared', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate())
    renderPage()
    await screen.findByText('₦15 per $1')

    const input = screen.getByPlaceholderText('e.g. 15')
    await userEvent.clear(input)

    expect(screen.getByRole('button', { name: 'Update markup' })).toBeDisabled()
  })

  it('shows an error banner when loading the rate fails', async () => {
    vi.mocked(configApi.getDollarRate).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'Boom', status: 500, detail: 'Boom', error_code: 'INTERNAL_ERROR' }, 'req-1'),
    )
    renderPage()

    expect(await screen.findByText('Boom')).toBeInTheDocument()
  })

  it('shows an error banner when updating the markup fails', async () => {
    vi.mocked(configApi.getDollarRate).mockResolvedValue(rate())
    vi.mocked(configApi.updateDollarRate).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'Rejected', status: 422, detail: 'Rejected', error_code: 'VALIDATION_ERROR' }, 'req-1'),
    )
    renderPage()
    await screen.findByText('₦15 per $1')

    await userEvent.click(screen.getByRole('button', { name: 'Update markup' }))

    expect(await screen.findByText('Rejected')).toBeInTheDocument()
  })
})
