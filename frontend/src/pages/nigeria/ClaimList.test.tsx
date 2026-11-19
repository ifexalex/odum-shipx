import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { claimsApi } from '../../api/claims'
import { ClaimList } from './ClaimList'

vi.mock('../../api/claims', () => ({
  claimsApi: { list: vi.fn(), stats: vi.fn(), get: vi.fn(), file: vi.fn(), startInspection: vi.fn(), resolve: vi.fn() },
  missingItemsApi: { list: vi.fn(), get: vi.fn(), update: vi.fn() },
  seizedItemsApi: { list: vi.fn(), get: vi.fn(), update: vi.fn() },
  presignedUploadApi: { getUrl: vi.fn() },
}))

function makeCtx(): SessionContextValue {
  const session: Session = {
    tenantId: 't1', userId: 'u1', role: 'nigeria_office_staff', roles: ['nigeria_office_staff'],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null,
    readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  name: null,
  }
  return { session, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }
}

const CLAIM_STUB = {
  id: 'aaaabbbb-cccc-dddd-eeee-111122223333',
  reference: 'DC-20260615-001',
  status: 'filed' as const,
  container_id: null,
  container_number: 'ACME001',
  customer_id: null,
  customer_name: 'Ngozi Okonkwo',
  description: 'Water damage to carton',
  inspection_method: null,
  cartons_affected: ['C001', 'C002'],
  upload_urls: null,
  created_at: '2026-06-15T10:00:00Z',
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SessionContext.Provider value={makeCtx()}><ClaimList /></SessionContext.Provider></MemoryRouter>
    </QueryClientProvider>,
  )
}

const CLAIM_STATS_STUB = {
  total: 1, open: 1, under_inspection: 0, resolved_30d: 0,
  filed: 1, pending_resolution: 0, resolved: 0, closed: 0,
}

beforeEach(() => {
  vi.mocked(claimsApi.list).mockReset()
  vi.mocked(claimsApi.stats).mockReset()
  vi.mocked(claimsApi.stats).mockResolvedValue(CLAIM_STATS_STUB)
})

describe('ClaimList', () => {
  it('renders claims from the API', async () => {
    vi.mocked(claimsApi.list).mockResolvedValue({
      data: [CLAIM_STUB],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('C001')).toBeInTheDocument())
    // 'Filed' matches both column header and status badge — scope to the badge
    expect(within(screen.getByRole('table')).getAllByText('Filed').length).toBeGreaterThanOrEqual(1)
  })

  it('loads stats (limit 500) + paginated table, and refetches the table with status on chip click', async () => {
    vi.mocked(claimsApi.list).mockResolvedValue({
      data: [CLAIM_STUB],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    // Two data paths: a stats query (limit 500) and the cursor-paginated table.
    await waitFor(() => expect(claimsApi.stats).toHaveBeenCalled())
    await waitFor(() => expect(claimsApi.list).toHaveBeenCalledWith({ cursor: undefined }))
    // Chip click refetches the table server-side with the status filter.
    await userEvent.click(screen.getByRole('button', { name: /Resolved/ }))
    await waitFor(() => expect(claimsApi.list).toHaveBeenCalledWith({ status: 'resolved', cursor: undefined }))
  })

  it('shows empty state', async () => {
    vi.mocked(claimsApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    renderPage()
    await waitFor(() => expect(screen.getByText(/No claims match/)).toBeInTheDocument())
  })

  it('sorts by reference ascending when the Claim ID header is clicked', async () => {
    // Empty table so 'Filed' only matches the column header, not a status badge.
    vi.mocked(claimsApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    renderPage()
    await waitFor(() => expect(claimsApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByText('Claim ID'))
    await waitFor(() =>
      expect(claimsApi.list).toHaveBeenCalledWith({ cursor: undefined, sort: 'reference', direction: 'asc' }),
    )
  })

  it('sorts by created_at descending by default when the Filed header is clicked', async () => {
    // 'Filed' also matches the top status chip — scope to the table header.
    vi.mocked(claimsApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    renderPage()
    await waitFor(() => expect(claimsApi.stats).toHaveBeenCalled())

    await userEvent.click(within(screen.getByRole('table')).getByText('Filed'))
    await waitFor(() =>
      expect(claimsApi.list).toHaveBeenCalledWith({ cursor: undefined, sort: 'created_at', direction: 'desc' }),
    )
  })

  // Ground-truth gap found live, reported by the user: "I want all the
  // filters that use calendar to allow date range... check all pages where
  // we are using calendar filter." The "Last 30 days" button here was a
  // static label with no onClick at all, and neither the frontend nor the
  // backend (`list_damage_claims`) supported a date filter to back it.
  it('a date-range preset and a custom From/To both filter by created_after/created_before', async () => {
    vi.mocked(claimsApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    renderPage()
    await waitFor(() => expect(claimsApi.stats).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(await screen.findByRole('option', { name: /last 30 days/i }))
    await waitFor(() =>
      expect(claimsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ created_after: expect.any(String) })),
    )

    await userEvent.click(screen.getByRole('button', { name: /^Filed:/ }))

    await userEvent.type(screen.getByLabelText('From'), '2026-01-01')
    await userEvent.type(screen.getByLabelText('To'), '2026-01-31')
    await waitFor(() =>
      expect(claimsApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ created_after: '2026-01-01', created_before: '2026-01-31' }),
      ),
    )
  })
})
