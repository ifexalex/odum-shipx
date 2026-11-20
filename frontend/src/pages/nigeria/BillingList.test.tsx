import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { billingApi } from '../../api/billing'
import { ApiError } from '../../api/client'
import { BillingList } from './BillingList'

vi.mock('../../api/billing', () => ({
  billingApi: { list: vi.fn(), exportList: vi.fn(), stats: vi.fn(), listForCustomer: vi.fn(), recordPayment: vi.fn(), cancel: vi.fn(), applyCarryover: vi.fn(), unbilled: vi.fn(), generateForContainer: vi.fn() },
  disputeApi: { list: vi.fn(), acknowledge: vi.fn(), resolve: vi.fn(), reject: vi.fn() },
  carryoverApi: { list: vi.fn(), exempt: vi.fn() },
}))

function makeSession(role = 'nigeria_office_staff'): Session {
  return {
    tenantId: 't1',
    userId: 'u1',
    name: null,
    role: role as Session['role'],
    roles: [role as Session['role']],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
}

function makeCtx(role = 'nigeria_office_staff'): SessionContextValue {
  return {
    session: makeSession(role),
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
  }
}

function makeBillingRecord(overrides = {}) {
  return {
    id: 'b1',
    container_id: 'c1',
    container_number: 'ACME001',
    total_cbm: '2.5',
    cbm_rate_usd: '45',
    dollar_rate: '1550',
    subtotal_usd: '112.50',
    subtotal_ngn: '174375',
    misc_fees: [],
    misc_fees_ngn: 0,
    adjustments_ngn: '0',
    carryover_ngn: 0,
    storage_fees_ngn: 0,
    total_due_ngn: '174375.00',
    total_paid_ngn: '0',
    outstanding_ngn: '174375.00',
    payment_status: 'unpaid' as const,
    released_with_outstanding: false,
    billed_at: null,
    payments: [],
    carryovers: [],
    _active_disputes: [],
    ...overrides,
  }
}

function renderPage(role = 'nigeria_office_staff') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SessionContext.Provider value={makeCtx(role)}>
          <BillingList />
        </SessionContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const STATS_STUB = {
  outstanding_ngn: '0', paid_this_month_ngn: '0', overdue: 0, total: 1,
  unpaid: 1, partially_paid: 0, paid: 0, overpaid: 0, waived: 0, released_with_outstanding: 0,
}

beforeEach(() => {
  vi.mocked(billingApi.list).mockReset()
  vi.mocked(billingApi.stats).mockReset()
  vi.mocked(billingApi.stats).mockResolvedValue(STATS_STUB)
})

describe('BillingList', () => {
  it('renders billing records from the API', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [makeBillingRecord()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('ACME001')).toBeInTheDocument())
    // 'Unpaid' matches the chip button AND the badge — scope to the table
    expect(within(screen.getByRole('table')).getByText('Unpaid')).toBeInTheDocument()
  })

  it('loads stats + paginated table, and refetches the table with status on chip click', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [makeBillingRecord()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    // Two data paths: the stats endpoint and the cursor-paginated table.
    await waitFor(() => expect(billingApi.stats).toHaveBeenCalled())
    await waitFor(() => expect(billingApi.list).toHaveBeenCalledWith({ cursor: undefined }))
    // Chip click refetches the table server-side with the status filter.
    await userEvent.click(screen.getByRole('button', { name: /Unpaid/ }))
    await waitFor(() => expect(billingApi.list).toHaveBeenCalledWith({ status: 'unpaid', cursor: undefined }))
  })

  it('shows empty state when no records match', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText(/No billing records match/)).toBeInTheDocument())
  })

  it('sorts by invoice_number ascending when the Reference header is clicked', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(billingApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByText('Reference'))
    await waitFor(() =>
      expect(billingApi.list).toHaveBeenCalledWith({ cursor: undefined, sort: 'invoice_number', direction: 'asc' }),
    )
  })

  it('sorts by billed_at descending by default when the Billed header is clicked', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(billingApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByText('Billed'))
    await waitFor(() =>
      expect(billingApi.list).toHaveBeenCalledWith({ cursor: undefined, sort: 'billed_at', direction: 'desc' }),
    )

    // A second click toggles to ascending.
    await userEvent.click(screen.getByText('Billed'))
    await waitFor(() =>
      expect(billingApi.list).toHaveBeenCalledWith({ cursor: undefined, sort: 'billed_at', direction: 'asc' }),
    )
  })

  // Ground-truth gap found live, reported by the user: "let's double check
  // the billing details filters and date ranges search and other filters are
  // correctly doing what they should do." The "calendar" button and
  // "Filters" button rendered with no onClick — pure dead UI — and neither
  // the frontend BillingListParams type nor the backend query-param parsing
  // supported a date range at all.
  it('the date-range button actually filters the table by billed_at', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(billingApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(await screen.findByRole('option', { name: /last 7 days/i }))

    await waitFor(() =>
      expect(billingApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ created_after: expect.any(String) }),
      ),
    )
  })

  it('a custom From/To date range is sent as created_after/created_before, overriding the preset', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(billingApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(await screen.findByRole('option', { name: /last 30 days/i }))
    await waitFor(() =>
      expect(billingApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ created_after: expect.any(String) })),
    )

    await userEvent.click(screen.getByRole('button', { name: /^Billed:/ }))

    await userEvent.type(screen.getByLabelText('From'), '2026-01-01')
    await waitFor(() =>
      expect(billingApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ created_after: '2026-01-01' })),
    )
    // The button says the custom range is what applies.
    expect(screen.getByRole('button', { name: /since/i })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('To'), '2026-01-31')
    await waitFor(() =>
      expect(billingApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ created_after: '2026-01-01', created_before: '2026-01-31' }),
      ),
    )
  })

  it('the Filters panel multi-selects statuses, ANDed as a comma-separated list', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(billingApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: /^filters$/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /^unpaid$/i }))
    await userEvent.click(screen.getByRole('checkbox', { name: /^partial$/i }))

    await waitFor(() =>
      expect(billingApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'unpaid,partially_paid' }),
      ),
    )
  })

  it('Clear all filters in the panel resets status and search', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(billingApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: /Unpaid/ }))
    await waitFor(() =>
      expect(billingApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'unpaid' }),
      ),
    )

    await userEvent.click(screen.getByRole('button', { name: /^filters$/i }))
    await userEvent.click(screen.getByRole('button', { name: /clear all filters/i }))

    await waitFor(() =>
      expect(billingApi.list).toHaveBeenLastCalledWith({ cursor: undefined }),
    )
  })
})

describe('BillingList — Generate billing', () => {
  function renderWithTopBar(role: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SessionContext.Provider value={makeCtx(role)}>
            <>
              <BillingList />
            </>
          </SessionContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  beforeEach(() => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    vi.mocked(billingApi.unbilled).mockReset()
    vi.mocked(billingApi.unbilled).mockResolvedValue([
      { container_id: 'k1', container_number: 'ACME001', container_status: 'cleared', customer_id: 'c1', customer_name: 'Alice', total_cbm: '2.000' },
    ])
  })

  it('opens the container picker for Nigeria staff', async () => {
    renderWithTopBar('nigeria_office_staff')

    await userEvent.click(await screen.findByRole('button', { name: 'Generate billing' }))

    const dialog = await screen.findByRole('dialog', { name: 'Generate billing' })
    expect(await within(dialog).findByText('Alice')).toBeInTheDocument()
  })

  it('closes the picker with Cancel', async () => {
    renderWithTopBar('tenant_admin')

    await userEvent.click(await screen.findByRole('button', { name: 'Generate billing' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog', { name: 'Generate billing' })).not.toBeInTheDocument()
  })

  it('is not offered to a role that cannot generate invoices', async () => {
    renderWithTopBar('china_office_staff')

    await waitFor(() => expect(billingApi.list).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Generate billing' })).not.toBeInTheDocument()
  })
})

describe('BillingList — Export', () => {
  function renderWithTopBar(role: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SessionContext.Provider value={makeCtx(role)}>
            <>
              <BillingList />
            </>
          </SessionContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  const tooLarge = new ApiError(
    {
      type: 'about:blank',
      title: 'Unprocessable Entity',
      status: 422,
      detail: 'More than 10,000 invoices match. Narrow the filters (status, dates or search) and export again.',
      error_code: 'BUSINESS_RULE_VIOLATION',
      rule_id: 'EXPORT_TOO_LARGE',
    },
    null,
  )

  beforeEach(() => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [makeBillingRecord()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(billingApi.exportList).mockReset()
    vi.mocked(billingApi.exportList).mockResolvedValue(undefined)
  })

  it('exports the whole list as Excel from the primary button', async () => {
    renderWithTopBar('tenant_admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Export' }))
    await waitFor(() => expect(billingApi.exportList).toHaveBeenCalledWith({}, 'xlsx'))
  })

  it('offers CSV from the format picker', async () => {
    renderWithTopBar('tenant_admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Choose export format' }))
    await userEvent.click(screen.getByRole('button', { name: /CSV/ }))
    await waitFor(() => expect(billingApi.exportList).toHaveBeenCalledWith({}, 'csv'))
  })

  it('exports the filters on screen at the moment of the click, not the ones it opened with', async () => {
    renderWithTopBar('tenant_admin')
    await screen.findByText('ACME001')
    // The button is placed in the top bar once, on mount; it must still see filters chosen afterwards.
    await userEvent.click(screen.getByRole('button', { name: /Unpaid/ }))
    await userEvent.type(screen.getByPlaceholderText(/Reference, customer, container/), 'acme')
    await waitFor(() => expect(billingApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'unpaid', q: 'acme' })))

    await userEvent.click(screen.getByRole('button', { name: 'Export' }))

    await waitFor(() => expect(billingApi.exportList).toHaveBeenCalledWith({ status: 'unpaid', q: 'acme' }, 'xlsx'))
  })

  it('exports the same sort and date range the list is using', async () => {
    renderWithTopBar('tenant_admin')
    await screen.findByText('ACME001')
    await userEvent.click(screen.getByRole('button', { name: /Reference/ }))
    await waitFor(() => expect(billingApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'invoice_number' })))
    const listParams = vi.mocked(billingApi.list).mock.calls.at(-1)?.[0] ?? {}

    await userEvent.click(screen.getByRole('button', { name: 'Export' }))

    await waitFor(() => expect(billingApi.exportList).toHaveBeenCalled())
    const [exported] = vi.mocked(billingApi.exportList).mock.calls[0]!
    expect(exported).toEqual({ sort: listParams.sort, direction: listParams.direction })
  })

  it('says why a refused export was refused, and lets the message be dismissed', async () => {
    vi.mocked(billingApi.exportList).mockRejectedValue(tooLarge)
    renderWithTopBar('tenant_admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Export' }))

    const banner = await screen.findByText(/Couldn't export invoices/)
    expect(banner).toBeInTheDocument()
    expect(screen.getByText(/More than 10,000 invoices match/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(screen.queryByText(/Couldn't export invoices/)).not.toBeInTheDocument()
  })

  it('clears an old failure when the next export is started', async () => {
    vi.mocked(billingApi.exportList).mockRejectedValueOnce(tooLarge).mockResolvedValueOnce(undefined)
    renderWithTopBar('tenant_admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Export' }))
    await screen.findByText(/Couldn't export invoices/)

    await userEvent.click(screen.getByRole('button', { name: 'Export' }))

    await waitFor(() => expect(screen.queryByText(/Couldn't export invoices/)).not.toBeInTheDocument())
  })

  it('is not offered to Nigeria office staff, who see the same list but not this button', async () => {
    renderWithTopBar('nigeria_office_staff')
    await waitFor(() => expect(billingApi.list).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Export' })).not.toBeInTheDocument()
  })
})

