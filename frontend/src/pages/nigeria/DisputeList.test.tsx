import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { disputeApi } from '../../api/billing'
import { DisputeList } from './DisputeList'

vi.mock('../../api/billing', () => ({
  billingApi: { list: vi.fn(), listForCustomer: vi.fn(), recordPayment: vi.fn(), cancel: vi.fn(), applyCarryover: vi.fn() },
  disputeApi: { list: vi.fn(), acknowledge: vi.fn(), resolve: vi.fn(), reject: vi.fn() },
  carryoverApi: { list: vi.fn(), exempt: vi.fn() },
}))

function makeCtx(role = 'nigeria_office_staff'): SessionContextValue {
  const session: Session = {
    tenantId: 't1',
    userId: 'u1',
    role: role as Session['role'],
    roles: [role as Session['role']],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  name: null,
  }
  return { session, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }
}

const DISPUTE_STUB = {
  id: 'd1',
  billing_id: 'aaaabbbb-cccc-dddd-eeee-111122223333',
  original_cbm: '2.5',
  corrected_cbm: null,
  status: 'submitted' as const,
  submitted_at: '2026-06-15T10:00:00Z',
}

beforeEach(() => {
  vi.mocked(disputeApi.list).mockReset()
})

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('DisputeList', () => {
  it('renders disputes', async () => {
    vi.mocked(disputeApi.list).mockResolvedValue({
      data: [DISPUTE_STUB],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    render(
      <QueryClientProvider client={__qc()}><MemoryRouter>
        <SessionContext.Provider value={makeCtx()}>
          <DisputeList />
        </SessionContext.Provider>
      </MemoryRouter></QueryClientProvider>,
    )
    // 'Submitted' appears both as a chip and as a badge — scope to the table
    // 'Submitted' is also a column header, so wait on the unique CBM value instead.
    expect(await screen.findByText('2.5')).toBeInTheDocument()
  })

  it('refetches with status filter on chip click', async () => {
    vi.mocked(disputeApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    render(
      <QueryClientProvider client={__qc()}><MemoryRouter>
        <SessionContext.Provider value={makeCtx()}>
          <DisputeList />
        </SessionContext.Provider>
      </MemoryRouter></QueryClientProvider>,
    )
    await waitFor(() => expect(disputeApi.list).toHaveBeenCalledWith({ cursor: undefined }))
    await userEvent.click(screen.getByText('Escalated to China'))
    await waitFor(() => expect(disputeApi.list).toHaveBeenCalledWith({ status: 'escalated_china', cursor: undefined }))
  })

  it('shows empty state', async () => {
    vi.mocked(disputeApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    render(
      <QueryClientProvider client={__qc()}><MemoryRouter>
        <SessionContext.Provider value={makeCtx()}>
          <DisputeList />
        </SessionContext.Provider>
      </MemoryRouter></QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText(/No disputes match/)).toBeInTheDocument())
  })
})
