import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session, UserRole } from '../../auth/types'
import { ApiError } from '../../api/client'
import { containersApi, type Container } from '../../api/tracking'
import { ContainerList } from './ContainerList'

vi.mock('../../api/tracking', () => ({
  containersApi: { list: vi.fn(), stats: vi.fn(), exportList: vi.fn() },
}))

function makeSession(role: UserRole): Session {
  return {
    tenantId: 't1',
    userId: 'u1',
    name: null,
    role,
    roles: [role],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
}

function makeContextValue(role: UserRole): SessionContextValue {
  return {
    session: makeSession(role),
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
}

function renderPage(role: UserRole) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeContextValue(role)}>
        <MemoryRouter>
          <>
            <ContainerList />
          </>
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

const containerStub: Container = {
  id: 'c1',
  tenant_id: 't1',
  container_number: 'MSCU1234567',
  parcel_number: null,
  origin: 'China',
  destination: 'Nigeria',
  ship_date: null,
  estimated_arrival_date: '2026-08-14',
  actual_arrival_date: null,
  status: 'in_transit',
  notes: null,
  created_by: 'staff-1',
  created_at: '2026-07-25',
  updated_at: '2026-07-25',
  vessel_name: null,
  voyage_number: null,
  shipping_line: null,
  seal_number: null,
  container_type: null,
  capacity_cbm: null,
  recommended_cbm: null,
  created_by_name: null,
}

describe('ContainerList', () => {
  const CONTAINER_STATS_STUB = {
    total: 1, loading: 1, sealed: 0, in_transit: 0, arrived: 0, customs_clearance: 0,
    cleared: 0, at_warehouse: 0, fully_released: 0, cancelled: 0, cleared_30d: 0,
  }

  beforeEach(() => {
    vi.mocked(containersApi.list).mockReset()
    vi.mocked(containersApi.stats).mockReset()
    vi.mocked(containersApi.stats).mockResolvedValue(CONTAINER_STATS_STUB)
  })

  it('renders containers returned by the API', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [containerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('MSCU1234567')).toBeInTheDocument())
  })

  it('shows container utilization (packed CBM + % of capacity) when capacity is known', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [{ ...containerStub, capacity_cbm: '76.00', total_cbm_packed: '68.40' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    renderPage('china_office_staff')
    const row = (await screen.findByText('MSCU1234567')).closest('tr')!
    expect(within(row).getByText('68.400')).toBeInTheDocument()
    expect(within(row).getByText('90%')).toBeInTheDocument() // 68.4 / 76 ≈ 90%
  })

  it('falls back to the container-type capacity estimate when no preset is set', async () => {
    // "40ft HC" → ~76 m³ estimate; 38.0 packed → 50%.
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [{ ...containerStub, capacity_cbm: null, container_type: "40' High Cube (HC)", total_cbm_packed: '38.00' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    renderPage('china_office_staff')
    const row = (await screen.findByText('MSCU1234567')).closest('tr')!
    expect(within(row).getByText('50%')).toBeInTheDocument()
  })

  it('shows just the packed CBM (no %) when capacity is unknown', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [{ ...containerStub, capacity_cbm: null, container_type: null, total_cbm_packed: '42.00' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    renderPage('china_office_staff')
    const row = (await screen.findByText('MSCU1234567')).closest('tr')!
    expect(within(row).getByText('42.000')).toBeInTheDocument()
    expect(within(row).queryByText(/%$/)).toBeNull()
  })

  it('shows the create container action only for china_office_staff', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('Create container')).toBeInTheDocument())
  })

  it('hides the create container action for nigeria_office_staff', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalled())
    expect(screen.queryByText('Create container')).not.toBeInTheDocument()
  })

  it('shows a positive empty state when there are no containers', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText(/create one to get started/i)).toBeInTheDocument())
  })

  it('shows an error banner when the API call fails', async () => {
    vi.mocked(containersApi.list).mockRejectedValue(new Error('boom'))
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText(/couldn't load containers/i)).toBeInTheDocument())
  })

  it('re-fetches with a status filter when a chip is clicked', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    // One call on mount: the paginated table (stats loads via containersApi.stats)
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByRole('button', { name: /in transit/i }))
    // Third call: paginated list re-fetch with the status filter
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))
    expect(vi.mocked(containersApi.list).mock.calls[1]?.[0]).toMatchObject({ status: 'in_transit' })
  })

  it('debounces the table search box instead of firing a request per keystroke', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    await userEvent.type(screen.getByPlaceholderText(/container number, vessel name, voyage/i), 'MSCU')

    // No new call fires immediately per keystroke.
    expect(containersApi.list).toHaveBeenCalledTimes(1)

    // After the debounce window, exactly one extra call fires with the full query.
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))
    expect(vi.mocked(containersApi.list).mock.calls[1]?.[0]).toMatchObject({ q: 'MSCU' })
  })

  it('filters by created date when a "Last 30 days" preset is selected, and clears when set back to All time', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    // Defaults to "All time" — no date filter applied on load.
    expect(screen.getByRole('button', { name: /all time/i })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(screen.getByRole('option', { name: /last 30 days/i }))

    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))
    const call = vi.mocked(containersApi.list).mock.calls[1]?.[0] as { created_after?: string }
    expect(call.created_after).toBeDefined()

    // Reverting to "All time" drops the filter and shows everything again.
    await userEvent.click(screen.getByRole('button', { name: /last 30 days/i }))
    await userEvent.click(screen.getByRole('option', { name: /^all time$/i }))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(3))
    const clearedCall = vi.mocked(containersApi.list).mock.calls[2]?.[0] as { created_after?: string }
    expect(clearedCall.created_after).toBeUndefined()
  })

  // Ground-truth gap found live, reported by the user: "I want all the
  // filters that use calendar to allow date range... include date filter to
  // them." A preset-only "last N days" button can't answer "everything
  // created on this one specific day" — every calendar filter now pairs its
  // preset with an exact custom From/To range, and a custom date always
  // overrides and clears the preset.
  it('a custom From/To date range is sent as created_after/created_before, overriding the preset', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(screen.getByRole('option', { name: /last 30 days/i }))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))

    await userEvent.click(screen.getByRole('button', { name: /^Created:/ }))

    await userEvent.type(screen.getByLabelText('From'), '2026-01-01')
    await waitFor(() => {
      const call = vi.mocked(containersApi.list).mock.calls.at(-1)?.[0] as {
        created_after?: string
      }
      expect(call.created_after).toBe('2026-01-01')
    })
    // The button says the custom range is what applies.
    expect(screen.getByRole('button', { name: /since/i })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('To'), '2026-01-31')
    await waitFor(() => {
      const call = vi.mocked(containersApi.list).mock.calls.at(-1)?.[0] as {
        created_after?: string
        created_before?: string
      }
      expect(call.created_after).toBe('2026-01-01')
      expect(call.created_before).toBe('2026-01-31')
    })
  })

  it('the Filters panel opens a real control and "Clear all filters" resets status/search/date state', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    // Set a status filter first (panel closed — clicking a chip while the
    // Filters popover is open would hit its click-away overlay instead, same
    // as the existing ExportButton dropdown pattern).
    await userEvent.click(screen.getByRole('button', { name: /in transit/i }))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))

    await userEvent.click(screen.getByRole('button', { name: /^filters$/i }))
    expect(screen.getByRole('dialog', { name: /filters/i })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /clear all filters/i }))

    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(3))
    const clearedCall = vi.mocked(containersApi.list).mock.calls[2]?.[0] as { status?: string }
    expect(clearedCall.status).toBeUndefined()
  })

  it('sorts by container number ascending, then descending, when the Container header is clicked twice', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByText('Container'))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))
    expect(vi.mocked(containersApi.list).mock.calls[1]?.[0]).toMatchObject({
      sort: 'container_number', direction: 'asc',
    })

    await userEvent.click(screen.getByText('Container'))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(3))
    expect(vi.mocked(containersApi.list).mock.calls[2]?.[0]).toMatchObject({
      sort: 'container_number', direction: 'desc',
    })
  })

  it('sorts by ETA ascending by default (soonest arrival first)', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByText('ETA'))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))
    expect(vi.mocked(containersApi.list).mock.calls[1]?.[0]).toMatchObject({
      sort: 'estimated_arrival_date', direction: 'asc',
    })
  })

  it('the Filters panel has a granular status multi-select and an "Arriving" ETA range, with no duplicate date-range control', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByRole('button', { name: /^filters$/i }))
    const dialog = screen.getByRole('dialog', { name: /filters/i })

    // All 9 individual statuses are selectable here — distinct from the
    // grouped quick-access chips above the table.
    expect(within(dialog).getByRole('checkbox', { name: /customs clearance/i })).toBeInTheDocument()
    expect(within(dialog).getByRole('checkbox', { name: /cancelled/i })).toBeInTheDocument()

    // The duplicate date-created control from row 7.36 is gone — that control
    // now lives only in the standalone calendar button.
    expect(within(dialog).queryByText(/date created/i)).not.toBeInTheDocument()

    // A real, distinct "Arriving" (ETA range) filter dimension.
    expect(within(dialog).getByRole('option', { name: /arriving in 30 days/i })).toBeInTheDocument()
  })

  it('selecting a status in the Filters panel multi-select re-fetches with that status and overrides the top chip selection', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByRole('button', { name: /^filters$/i }))
    const dialog = screen.getByRole('dialog', { name: /filters/i })
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /^sealed$/i }))

    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))
    expect(vi.mocked(containersApi.list).mock.calls[1]?.[0]).toMatchObject({ status: 'sealed' })

    // The "Packed" chip (which also maps to status=sealed) no longer reads as
    // active for a different, unrelated combination — selecting a second,
    // different status here proves the panel is the source of truth.
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /^cancelled$/i }))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(3))
    expect(vi.mocked(containersApi.list).mock.calls[2]?.[0]).toMatchObject({ status: 'sealed,cancelled' })
  })

  it('"Clear all filters" resets the status multi-select and ETA range, but leaves the standalone date-created button untouched', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))

    // Set the standalone date-created button to "Last 30 days" first.
    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(screen.getByRole('option', { name: /last 30 days/i }))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(2))

    // Set an ETA preset inside the Filters panel, then clear.
    await userEvent.click(screen.getByRole('button', { name: /^filters$/i }))
    const dialog = screen.getByRole('dialog', { name: /filters/i })
    await userEvent.click(within(dialog).getByRole('option', { name: /arriving in 30 days/i }))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(3))

    await userEvent.click(screen.getByRole('button', { name: /clear all filters/i }))
    await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(4))

    const clearedCall = vi.mocked(containersApi.list).mock.calls[3]?.[0] as {
      eta_after?: string; eta_before?: string; created_after?: string
    }
    expect(clearedCall.eta_after).toBeUndefined()
    expect(clearedCall.eta_before).toBeUndefined()
    // The standalone date button's own filter survives the panel's "Clear all filters".
    expect(clearedCall.created_after).toBeDefined()
    expect(screen.getByRole('button', { name: /last 30 days/i })).toBeInTheDocument()
  })

  describe('Export', () => {
    const emptyPage = { data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }

    beforeEach(() => {
      vi.mocked(containersApi.list).mockResolvedValue(emptyPage)
      vi.mocked(containersApi.exportList).mockReset()
      vi.mocked(containersApi.exportList).mockResolvedValue(undefined)
    })

    it.each(['china_office_staff', 'nigeria_office_staff', 'tenant_admin'] as const)(
      '%s, who can see the list, can export it',
      async (role) => {
        renderPage(role)
        await userEvent.click(await screen.findByRole('button', { name: 'Export' }))
        await waitFor(() => expect(containersApi.exportList).toHaveBeenCalledTimes(1))
        expect(vi.mocked(containersApi.exportList).mock.calls[0]![1]).toBe('xlsx')
      },
    )

    it('only China staff are offered Create container', async () => {
      renderPage('nigeria_office_staff')
      await screen.findByRole('button', { name: 'Export' })
      expect(screen.queryByRole('button', { name: 'Create container' })).not.toBeInTheDocument()
    })

    it('exports the filters on screen at the moment of the click, not the ones it opened with', async () => {
      renderPage('china_office_staff')
      await waitFor(() => expect(containersApi.list).toHaveBeenCalledTimes(1))
      // The button is placed in the top bar once, on mount; it must still see filters chosen afterwards.
      await userEvent.click(screen.getByRole('button', { name: /in transit/i }))
      await userEvent.type(screen.getByPlaceholderText(/container number, vessel name, voyage/i), 'MSCU')
      await waitFor(() => expect(containersApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'in_transit', q: 'MSCU' })))

      await userEvent.click(screen.getByRole('button', { name: 'Export' }))

      await waitFor(() => expect(containersApi.exportList).toHaveBeenCalled())
      expect(vi.mocked(containersApi.exportList).mock.calls[0]![0]).toMatchObject({ status: 'in_transit', q: 'MSCU' })
    })

    it('does not send paging parameters: the export is the whole list', async () => {
      renderPage('china_office_staff')
      await userEvent.click(await screen.findByRole('button', { name: 'Export' }))
      await waitFor(() => expect(containersApi.exportList).toHaveBeenCalled())
      const params = vi.mocked(containersApi.exportList).mock.calls[0]![0] as Record<string, unknown>
      expect(params).not.toHaveProperty('cursor')
      expect(params).not.toHaveProperty('limit')
    })

    it('says why a refused export was refused', async () => {
      vi.mocked(containersApi.exportList).mockRejectedValue(
        new ApiError(
          {
            type: 'about:blank',
            title: 'Unprocessable Entity',
            status: 422,
            detail: 'More than 10,000 containers match. Narrow the filters (status, dates or search) and export again.',
            error_code: 'BUSINESS_RULE_VIOLATION',
            rule_id: 'EXPORT_TOO_LARGE',
          },
          null,
        ),
      )
      renderPage('china_office_staff')
      await userEvent.click(await screen.findByRole('button', { name: 'Export' }))
      expect(await screen.findByText(/Couldn't export containers/)).toBeInTheDocument()
      expect(screen.getByText(/More than 10,000 containers match/)).toBeInTheDocument()
    })
  })
})
