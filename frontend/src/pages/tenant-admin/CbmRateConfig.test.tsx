/**
 * CBM rate (2026-09-20) — a tenant_admin can now choose the currency
 * (Naira/Dollar) and whether the rate is a single flat number or three
 * separate carton/bag/bale rates. "Flat" is enforced server-side as
 * bag_rate = bale_rate = carton_rate, not a separate code path.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { configApi, type CbmRateConfig as CbmRateConfigShape } from '../../api/tenantManagement'
import { CbmRateConfig } from './CbmRateConfig'
import { withQuery } from '../../test/queryWrapper'

function renderPage(): ReturnType<typeof render> {
  return render(withQuery(
    <MemoryRouter>
      <CbmRateConfig />
    </MemoryRouter>,
  ))
}

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    configApi: {
      ...original.configApi,
      getCbmRate: vi.fn(),
      updateCbmRate: vi.fn(),
      rateHistory: vi.fn(),
    },
  }
})

function rate(overrides: Partial<CbmRateConfigShape> = {}): CbmRateConfigShape {
  return {
    currency: 'usd',
    rate_mode: 'flat',
    carton_rate: 45,
    bag_rate: 45,
    bale_rate: 45,
    effective_from: '2026-09-18T09:00:00Z',
    min_cbm_per_item: 0.1,
    ...overrides,
  }
}

describe('CbmRateConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.rateHistory).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
  })

  it('shows the flat rate as one line', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(rate())
    renderPage()

    expect(await screen.findByText('$45.00 per CBM')).toBeInTheDocument()
    expect(screen.getByText('USD')).toBeInTheDocument()
    // "Single rate" appears both in the mode Kvp and the toggle button.
    expect(screen.getAllByText('Single rate')).toHaveLength(2)
  })

  it('shows a per-package-type breakdown line when rate_mode is per_package_type', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(
      rate({ rate_mode: 'per_package_type', currency: 'ngn', carton_rate: 45000, bag_rate: 45000, bale_rate: 60000 }),
    )
    renderPage()

    expect(await screen.findByText('Cartons ₦45000.00 · Bags ₦45000.00 · Bales ₦60000.00')).toBeInTheDocument()
    expect(screen.getAllByText('By package type')).toHaveLength(2)
  })

  it('pre-fills the form with the current currency and mode', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(rate({ currency: 'ngn' }))
    renderPage()
    await screen.findByText('₦45.00 per CBM')

    expect(screen.getByRole('button', { name: 'Naira (₦)' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('e.g. 45')).toHaveValue(45)
  })

  it('switching to "By package type" shows three separate rate inputs', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(rate())
    renderPage()
    await screen.findByText('$45.00 per CBM')

    await userEvent.click(screen.getByRole('button', { name: 'By package type' }))

    expect(screen.getByText('Cartons ($ per CBM)')).toBeInTheDocument()
    expect(screen.getByText('Bags ($ per CBM)')).toBeInTheDocument()
    expect(screen.getByText('Bales ($ per CBM)')).toBeInTheDocument()
    expect(screen.getByText(/any other package type.*bills at the carton rate/i)).toBeInTheDocument()
  })

  it('submits a flat-rate update, mirroring carton_rate into bag_rate/bale_rate', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(rate())
    vi.mocked(configApi.updateCbmRate).mockResolvedValue(rate({ carton_rate: 50, bag_rate: 50, bale_rate: 50 }))
    renderPage()
    await screen.findByText('$45.00 per CBM')

    const input = screen.getByPlaceholderText('e.g. 45')
    await userEvent.clear(input)
    await userEvent.type(input, '50')
    await userEvent.click(screen.getByRole('button', { name: 'Update rate' }))

    await waitFor(() => expect(configApi.updateCbmRate).toHaveBeenCalledWith({
      currency: 'usd', rate_mode: 'flat', carton_rate: 50, bag_rate: 50, bale_rate: 50, min_cbm_per_item: 0.1,
    }))
    expect(await screen.findByText('CBM rate updated successfully.')).toBeInTheDocument()
    expect(screen.getByText('$50.00 per CBM')).toBeInTheDocument()
  })

  it('submits distinct per-package-type rates', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(rate())
    vi.mocked(configApi.updateCbmRate).mockResolvedValue(
      rate({ rate_mode: 'per_package_type', carton_rate: 45, bag_rate: 45, bale_rate: 60 }),
    )
    renderPage()
    await screen.findByText('$45.00 per CBM')

    await userEvent.click(screen.getByRole('button', { name: 'By package type' }))
    const baleInput = screen.getByLabelText('Bales ($ per CBM)')
    expect(baleInput).toBeTruthy()
    await userEvent.clear(baleInput!)
    await userEvent.type(baleInput!, '60')
    await userEvent.click(screen.getByRole('button', { name: 'Update rate' }))

    await waitFor(() => expect(configApi.updateCbmRate).toHaveBeenCalledWith({
      currency: 'usd', rate_mode: 'per_package_type', carton_rate: 45, bag_rate: 45, bale_rate: 60, min_cbm_per_item: 0.1,
    }))
  })

  it('disables Update rate when a required field is cleared in per-package-type mode', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(rate())
    renderPage()
    await screen.findByText('$45.00 per CBM')

    await userEvent.click(screen.getByRole('button', { name: 'By package type' }))
    const bagInput = screen.getByLabelText('Bags ($ per CBM)')
    await userEvent.clear(bagInput!)

    expect(screen.getByRole('button', { name: 'Update rate' })).toBeDisabled()
  })

  it('shows an error banner when loading the rate fails', async () => {
    vi.mocked(configApi.getCbmRate).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'Boom', status: 500, detail: 'Boom', error_code: 'INTERNAL_ERROR' }, 'req-1'),
    )
    renderPage()

    expect(await screen.findByText('Boom')).toBeInTheDocument()
  })

  it('shows an error banner when updating the rate fails', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValue(rate())
    vi.mocked(configApi.updateCbmRate).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'Rejected', status: 422, detail: 'Rejected', error_code: 'VALIDATION_ERROR' }, 'req-1'),
    )
    renderPage()
    await screen.findByText('$45.00 per CBM')

    await userEvent.click(screen.getByRole('button', { name: 'Update rate' }))

    expect(await screen.findByText('Rejected')).toBeInTheDocument()
  })
})
