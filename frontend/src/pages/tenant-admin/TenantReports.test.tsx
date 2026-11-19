import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { billingApi } from '../../api/billing'
import { TopBarContext } from '../../shell/TopBarContext'
import { TenantReports } from './TenantReports'

vi.mock('../../api/billing', () => ({ billingApi: { report: vi.fn() } }))

// The "When" date-range control lives in the shared TopBar action slot, not
// TenantReports' own render tree — same wrapper as china/ContainerList.test.tsx
// so tests can query it the same way the real StaffLayout would.
function TopBarWrapper({ children }: { children: ReactNode }) {
  const [suffix, setSuffix] = useState<string | null>(null)
  const [subtitle, setSubtitle] = useState<string | null>(null)
  const [actions, setActions] = useState<ReactNode | null>(null)
  return (
    <TopBarContext.Provider value={{ suffix, setSuffix, subtitle, setSubtitle, actions, setActions }}>
      {children}
      {actions && <div data-testid="topbar-actions">{actions}</div>}
    </TopBarContext.Provider>
  )
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <TopBarWrapper><TenantReports /></TopBarWrapper>
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
})
