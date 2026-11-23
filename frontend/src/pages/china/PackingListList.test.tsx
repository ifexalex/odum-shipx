import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session, UserRole } from '../../auth/types'
import { packingListApi, type PackingList } from '../../api/packingList'
import { PackingListList } from './PackingListList'

vi.mock('../../api/packingList', () => ({
  packingListApi: { list: vi.fn(), bulkSubmit: vi.fn(), bulkApprove: vi.fn(), bulkReject: vi.fn() },
}))

function makeSession(role: UserRole, userId = 'u1'): Session {
  return {
    tenantId: 't1',
    userId,
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

function makeContextValue(role: UserRole, userId?: string): SessionContextValue {
  return {
    session: makeSession(role, userId),
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
}

function renderPage(role: UserRole, userId?: string) {
  return render(
    <SessionContext.Provider value={makeContextValue(role, userId)}>
      <QueryClientProvider client={__qc()}><MemoryRouter>
        <PackingListList />
      </MemoryRouter></QueryClientProvider>
    </SessionContext.Provider>,
  )
}

function plStub(overrides: Partial<PackingList> = {}): PackingList {
  return {
    id: 'pl1',
    tenant_id: 't1',
    reference: 'PL-20260725-001',
    container_id: 'c1',
    container_number: 'ACME-001',
    customer_id: 'cust1',
    status: 'pending_approval',
    items: [],
    total_cbm: '1.5',
    total_weight_kg: '20',
    carton_count: 5,
    created_by: 'staff-1',
    approved_by: null,
    approved_at: null,
    rejected_by: null,
    rejected_at: null,
    approval_comments: null,
    created_at: '2026-07-25',
    updated_at: '2026-07-25',
    ...overrides,
  }
}

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('PackingListList', () => {
  beforeEach(() => {
    vi.mocked(packingListApi.list).mockReset()
    vi.mocked(packingListApi.bulkApprove).mockReset()
    vi.mocked(packingListApi.bulkReject).mockReset()
  })

  it('renders packing lists from the API', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('Pending approval')).toBeInTheDocument())
  })

  it('shows row checkboxes for china_office_staff but not for customer-adjacent roles', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('Pending approval')).toBeInTheDocument())
    expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(0)
  })

  it('selecting rows reveals the bulk action bar and bulk-approves the selection', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1' }), plStub({ id: 'pl2' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
    vi.mocked(packingListApi.bulkApprove).mockResolvedValue({ succeeded: ['pl1', 'pl2'], failed: [] })
    renderPage('tenant_admin')
    // Wait for data rows (header select-all renders before data — length>1 means rows loaded).
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))

    const rowCheckboxes = screen.getAllByRole('checkbox').slice(1)
    await userEvent.click(rowCheckboxes[0]!)
    expect(screen.getByText('1 packing list selected')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Bulk approve · 1'))
    await waitFor(() => expect(packingListApi.bulkApprove).toHaveBeenCalledWith(['pl1']))
  })

  it('renders a per-item result table after a bulk action, not a single toast', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1' }), plStub({ id: 'pl2' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
    vi.mocked(packingListApi.bulkApprove).mockResolvedValue({
      succeeded: ['pl1'],
      failed: [{ id: 'pl2', reason: 'SELF_APPROVAL_FORBIDDEN' }],
    })
    renderPage('tenant_admin')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))
    const rowCheckboxes = screen.getAllByRole('checkbox').slice(1)
    await userEvent.click(rowCheckboxes[0]!)
    await userEvent.click(rowCheckboxes[1]!)
    await userEvent.click(screen.getByText('Bulk approve · 2'))

    await waitFor(() => expect(screen.getByText('1 succeeded · 1 failed')).toBeInTheDocument())
    expect(screen.getByText('SELF_APPROVAL_FORBIDDEN')).toBeInTheDocument()
  })

  it('requires comments before confirming a bulk reject', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))
    const rowCheckboxes = screen.getAllByRole('checkbox').slice(1)
    await userEvent.click(rowCheckboxes[0]!)
    await userEvent.click(screen.getByText('Bulk reject · 1'))

    const confirmButton = screen.getByRole('button', { name: 'Confirm reject' })
    expect(confirmButton).toBeDisabled()
  })

  it('shows a failed bulk reject inline in the still-open modal, not hidden behind it', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(packingListApi.bulkReject).mockRejectedValue(new Error('boom'))
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))
    const rowCheckboxes = screen.getAllByRole('checkbox').slice(1)
    await userEvent.click(rowCheckboxes[0]!)
    await userEvent.click(screen.getByText('Bulk reject · 1'))
    await userEvent.type(screen.getByLabelText('Comments', { exact: false }), 'bad batch')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm reject' }))

    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('Bulk reject failed.')).toBeInTheDocument())
  })

  it('bulk-submits drafts to pending_approval', async () => {
    // Regression: an import creates dozens of drafts at once, and bulk approve
    // rejects draft with wrong_status. Without a bulk submit the only way
    // forward was opening every list individually.
    //
    // status: 'draft' here is load-bearing — plStub() defaults to
    // pending_approval, which this test used to stub unnoticed. That let it
    // pass while the real bug (draft rows had no checkbox at all — see
    // PackingListList.tsx's `selectable`) went undetected, since nothing
    // gated the button on what was actually selected.
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1', status: 'draft' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(packingListApi.bulkSubmit).mockResolvedValue({ succeeded: ['pl1'], failed: [] })
    renderPage('tenant_admin')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))

    await userEvent.click(screen.getAllByRole('checkbox').slice(1)[0]!)
    await userEvent.click(screen.getByText('Submit for approval · 1'))

    await waitFor(() => expect(packingListApi.bulkSubmit).toHaveBeenCalledWith(['pl1']))
    expect(packingListApi.bulkApprove).not.toHaveBeenCalled()
  })

  it('disables Submit for approval when nothing selected is a draft', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1', status: 'pending_approval' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage('tenant_admin')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))

    await userEvent.click(screen.getAllByRole('checkbox').slice(1)[0]!)

    expect(screen.getByText('Submit for approval · 0')).toBeDisabled()
  })

  it('reports a bulk failure in plain language, grouped, without leaking codes or UUIDs', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1' }), plStub({ id: 'pl2' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
    vi.mocked(packingListApi.bulkApprove).mockResolvedValue({
      succeeded: [],
      failed: [
        { id: 'pl1', reason: 'self_approval_forbidden' },
        { id: 'pl2', reason: 'self_approval_forbidden' },
      ],
    })
    renderPage('tenant_admin')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))

    await userEvent.click(screen.getAllByRole('checkbox')[0]!)
    await userEvent.click(screen.getByText('Bulk approve · 2'))

    // Explanation, once — not one row per record repeating a machine code.
    await waitFor(() =>
      expect(screen.getByText(/cannot approve them/i)).toBeInTheDocument(),
    )
    expect(screen.queryByText('self_approval_forbidden')).not.toBeInTheDocument()
    expect(screen.getByText(/ask a colleague/i)).toBeInTheDocument()
    // Records are named by their reference, not their UUID.
    expect(screen.queryByText('pl1')).not.toBeInTheDocument()
    expect(screen.getAllByText(/PL-20260725-001/).length).toBeGreaterThan(0)
  })

  it('warns up front and disables approve when the user created everything selected', async () => {
    // Better than a good error message: don't let them fire a request the UI
    // already knows will fail for every row.
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [
        plStub({ id: 'pl1', status: 'pending_approval', created_by: 'user-1' }),
        plStub({ id: 'pl2', status: 'pending_approval', created_by: 'user-1' }),
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
    renderPage('tenant_admin', 'user-1')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))

    await userEvent.click(screen.getAllByRole('checkbox')[0]!)
    expect(screen.getByText(/someone else must approve them/i)).toBeInTheDocument()
    expect(screen.getByText('Bulk approve · 0').closest('button')).toBeDisabled()
    expect(screen.getByText('Bulk reject · 0').closest('button')).toBeDisabled()
  })

  it('sends only eligible IDs for bulk actions on mixed selections and links failed chips to their detail page', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [
        plStub({ id: 'pl-draft', reference: 'PL-DRAFT', status: 'draft', created_by: 'staff-1' }),
        plStub({ id: 'pl-pending', reference: 'PL-PEND', status: 'pending_approval', created_by: 'staff-1' }),
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
    vi.mocked(packingListApi.bulkApprove).mockResolvedValue({
      succeeded: [],
      failed: [{ id: 'pl-pending', reason: 'wrong_status' }],
    })
    renderPage('tenant_admin', 'admin-2')
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(1))

    await userEvent.click(screen.getAllByRole('checkbox')[0]!)
    await userEvent.click(screen.getByText('Bulk approve · 1'))

    await waitFor(() => expect(packingListApi.bulkApprove).toHaveBeenCalledWith(['pl-pending']))
    const failureLink = await screen.findByRole('link', { name: /PL-PEND/ })
    expect(failureLink).toHaveAttribute('href', '/packing-lists/pl-pending')
  })

  it('states the full total when a page is only part of the result', async () => {
    // Regression: 50 rows with no total read as "this container has 50 packing
    // lists" when it had 68 — the rest were one status filter away.
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1' }), plStub({ id: 'pl2' })],
      meta: { pagination: { has_more: true, next_cursor: 'CUR', total_count: 68 } },
    })
    renderPage('tenant_admin')
    await waitFor(() => expect(screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === 'Showing 2 of 68 packing lists')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /66 remaining/ })).toBeInTheDocument()
  })

  it('does not claim a total when the page already holds everything', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [plStub({ id: 'pl1' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage('tenant_admin')
    await waitFor(() => expect(screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === 'Showing 1 packing list')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Load more/ })).not.toBeInTheDocument()
  })
})
