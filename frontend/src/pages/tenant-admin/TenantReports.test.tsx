import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { billingApi } from '../../api/billing'
import { ApiError } from '../../api/client'
import { TenantReports } from './TenantReports'

vi.mock('../../api/billing', () => ({ billingApi: { report: vi.fn(), exportReport: vi.fn() } }))

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <><TenantReports /></>
    </QueryClientProvider>,
  )
}

function emptyReport() {
  return {
    overview: {
      total_revenue_ngn: '0', total_cbm: '0', revenue_paid: '0', revenue_partially_paid: '0',
      revenue_unpaid: '0', revenue_released_with_outstanding: '0', revenue_waived: '0',
      containers_processed: 0, active_customers: 0,
    },
    claims: { total: 0, open: 0, resolved: 0 },
    container_pipeline: [],
    top_customers: [],
    container_billing: [],
  }
}

beforeEach(() => {
  vi.mocked(billingApi.report).mockReset().mockResolvedValue(emptyReport())
  vi.mocked(billingApi.exportReport).mockReset().mockResolvedValue(undefined)
})

describe('TenantReports', () => {
  it('loads report data with no date filter by default', async () => {
    renderPage()
    await waitFor(() => expect(billingApi.report).toHaveBeenCalled())
    expect(billingApi.report).toHaveBeenCalledWith(
      expect.objectContaining({ created_after: undefined, created_before: undefined }),
    )
  })

  // Ground-truth gap found live, reported by the user: "I want all the
  // filters that use calendar to allow date range... check all pages where
  // we are using calendar filter." The "Last 3 months" button here was a
  // static label with no onClick, and the whole report always fetched
  // unscoped data regardless of what the label implied.
  it('a date-range preset and a custom From/To scope billing/containers/claims together', async () => {
    renderPage()
    await waitFor(() => expect(billingApi.report).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(await screen.findByRole('option', { name: /last 90 days/i }))

    await waitFor(() =>
      expect(billingApi.report).toHaveBeenLastCalledWith(expect.objectContaining({ created_after: expect.any(String) })),
    )

    await userEvent.click(screen.getByRole('button', { name: /^Period:/ }))

    await userEvent.type(screen.getByLabelText('From'), '2026-01-01')
    await userEvent.type(screen.getByLabelText('To'), '2026-01-31')

    await waitFor(() =>
      expect(billingApi.report).toHaveBeenLastCalledWith(
        expect.objectContaining({ created_after: '2026-01-01', created_before: '2026-01-31' }),
      ),
    )
  })

  // Found 2026-11-20: both Export buttons on this page had no handler. The table's one now downloads every container
  // billed in the period; the top-bar one, which would have downloaded the same file, is gone.
  describe('Export (billing by container)', () => {
    it('is one button, beside the table, and exports Excel for the whole period by default', async () => {
      renderPage()
      await screen.findByText('CBM & billing by container')
      expect(screen.getAllByRole('button', { name: 'Export' })).toHaveLength(1)

      await userEvent.click(screen.getByRole('button', { name: 'Export' }))
      await waitFor(() => expect(billingApi.exportReport).toHaveBeenCalledWith({}, 'xlsx'))
    })

    it('exports the period on screen at the moment of the click, as CSV when chosen', async () => {
      renderPage()
      await screen.findByText('CBM & billing by container')
      await userEvent.click(screen.getByRole('button', { name: /^Period:/ }))
      await userEvent.type(screen.getByLabelText('From'), '2026-01-01')
      await userEvent.type(screen.getByLabelText('To'), '2026-01-31')
      await waitFor(() =>
        expect(billingApi.report).toHaveBeenLastCalledWith(expect.objectContaining({ created_before: '2026-01-31' })),
      )

      await userEvent.click(await screen.findByRole('button', { name: 'Choose export format' }))
      await userEvent.click(screen.getByRole('button', { name: /CSV/ }))
      await waitFor(() =>
        expect(billingApi.exportReport).toHaveBeenCalledWith({ created_after: '2026-01-01', created_before: '2026-01-31' }, 'csv'),
      )
    })

    it('says why a refused export was refused', async () => {
      vi.mocked(billingApi.exportReport).mockRejectedValue(
        new ApiError(
          {
            type: 'about:blank', title: 'Unprocessable', status: 422,
            detail: 'More than 10,000 containers match. Narrow the period and export again.',
            error_code: 'BUSINESS_RULE_VIOLATION', rule_id: 'EXPORT_TOO_LARGE',
          },
          null,
        ),
      )
      renderPage()
      await userEvent.click(await screen.findByRole('button', { name: 'Export' }))
      expect(await screen.findByText("Couldn't export the report")).toBeInTheDocument()
      expect(screen.getByText(/More than 10,000 containers match/)).toBeInTheDocument()
    })

    it('says when the table is only the top 200 and the export has the rest', async () => {
      const rows = Array.from({ length: 200 }, (_, i) => ({
        container_number: `MSCU${String(i).padStart(7, '0')}`, customers: 1, cbm: '1', billed: '1000',
        collected: '0', outstanding: '1000', cbm_rate_usd: '100', dollar_rate: '1500',
      }))
      vi.mocked(billingApi.report).mockResolvedValue({ ...emptyReport(), container_billing: rows })
      renderPage()
      expect(await screen.findByText(/The 200 containers billed most this period\. Export for every container\./)).toBeInTheDocument()
    })
  })
})
