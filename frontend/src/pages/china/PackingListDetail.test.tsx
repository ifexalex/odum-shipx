import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session, UserRole } from '../../auth/types'
import { packingListApi, type PackingList } from '../../api/packingList'
import { PackingListDetail } from './PackingListDetail'

vi.mock('../../api/packingList', () => ({
  packingListApi: { get: vi.fn(), approve: vi.fn(), reject: vi.fn(), update: vi.fn(), submit: vi.fn() },
}))

function makeSession(role: UserRole, userId: string): Session {
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

function makeContextValue(role: UserRole, userId: string): SessionContextValue {
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

function plStub(overrides: Partial<PackingList> = {}): PackingList {
  return {
    id: 'pl1',
    tenant_id: 't1',
    reference: 'PL-20260725-001',
    container_id: 'c1',
    container_number: 'ACME-001',
    customer_id: 'cust1',
    status: 'pending_approval',
    items: [
      {
        id: 'i1',
        packing_list_id: 'pl1',
        description: 'Electronics',
        weight_dispatch_kg: '12.500',
        weight_actual_kg: '12.800',
        carton_tag: 'SHX-00001',
        tracking_code: null,
        cbm: '0.030000',
        length_cm: '40.00',
        width_cm: '30.00',
        height_cm: '25.00',
        received_date: null,
        declared_value_usd: '380.00',
      },
    ],
    total_cbm: '0.03',
    total_weight_kg: '12.8',
    carton_count: 1,
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

function renderPage(role: UserRole, userId: string) {
  return render(
    withQuery(
      <SessionContext.Provider value={makeContextValue(role, userId)}>
        <MemoryRouter initialEntries={['/packing-lists/pl1']}>
          <Routes>
            <Route path="/packing-lists/:id" element={<PackingListDetail />} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>,
    ),
  )
}

describe('PackingListDetail', () => {
  beforeEach(() => {
    vi.mocked(packingListApi.get).mockReset()
    vi.mocked(packingListApi.approve).mockReset()
    vi.mocked(packingListApi.reject).mockReset()
    vi.mocked(packingListApi.update).mockReset()
    vi.mocked(packingListApi.submit).mockReset()
  })

  // Reject packing list: from the overflow menu (FD-24).
  async function openReject(): Promise<void> {
    await userEvent.click(await screen.findByRole('button', { name: 'More packing list actions' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Reject packing list' }))
  }

  it('shows approve/reject for an authorized non-creator on a pending list', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ created_by: 'staff-1' }))
    renderPage('china_office_staff', 'staff-2')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument())
    // Reject is in the overflow menu, not beside Approve (FD-24).
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull()
    await openReject()
  })

  it('hides approve/reject and explains why when the actor created the list (self-approval prevention)', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ created_by: 'staff-1' }))
    renderPage('china_office_staff', 'staff-1')
    await waitFor(() => expect(screen.getByText('Items')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
    expect(screen.getByText('Awaiting another approver')).toBeInTheDocument()
  })

  it('hides approve/reject for roles outside the approver set even on a pending list', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ created_by: 'staff-1' }))
    renderPage('nigeria_office_staff', 'staff-2')
    await waitFor(() => expect(screen.getByText('Items')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('approves on click', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ created_by: 'staff-1' }))
    vi.mocked(packingListApi.approve).mockResolvedValue(plStub({ status: 'approved', approved_by: 'staff-2' }))
    renderPage('china_office_staff', 'staff-2')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(packingListApi.approve).toHaveBeenCalledWith('pl1'))
  })

  it('requires comments before confirming a reject', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ created_by: 'staff-1' }))
    renderPage('china_office_staff', 'staff-2')
    await openReject()
    expect(screen.getByRole('button', { name: 'Confirm reject' })).toBeDisabled()
  })

  it('shows a failed reject inline in the still-open modal, not hidden behind it', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ created_by: 'staff-1' }))
    vi.mocked(packingListApi.reject).mockRejectedValue(new Error('boom'))
    renderPage('china_office_staff', 'staff-2')
    await openReject()
    await userEvent.type(screen.getByLabelText('Comments', { exact: false }), 'bad transition')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm reject' }))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(within(dialog).getByText('Could not reject this packing list.')).toBeInTheDocument(),
    )
  })

  it('shows edit & resubmit only when rejected, and resubmits via update+submit', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ status: 'rejected', created_by: 'staff-1' }))
    vi.mocked(packingListApi.update).mockResolvedValue(plStub({ status: 'draft' }))
    vi.mocked(packingListApi.submit).mockResolvedValue(plStub({ status: 'pending_approval' }))
    renderPage('china_office_staff', 'staff-1')
    await waitFor(() => expect(screen.getByText('Revise and resubmit')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Revise and resubmit'))
    await userEvent.click(screen.getByText('Save & resubmit'))
    await waitFor(() => expect(packingListApi.update).toHaveBeenCalledTimes(1))
    expect(packingListApi.submit).toHaveBeenCalledTimes(1)
  })

  it('does not show edit & resubmit on an approved list', async () => {
    vi.mocked(packingListApi.get).mockResolvedValue(plStub({ status: 'approved', approved_by: 'admin-1' }))
    renderPage('china_office_staff', 'staff-1')
    await waitFor(() => expect(screen.getByText('Items')).toBeInTheDocument())
    expect(screen.queryByText('Revise and resubmit')).not.toBeInTheDocument()
  })

  it('keeps each remaining row paired with its own carton tag after deleting an earlier row while editing', async () => {
    const baseItem = plStub().items[0]!
    vi.mocked(packingListApi.get).mockResolvedValue(
      plStub({
        status: 'rejected',
        created_by: 'staff-1',
        items: [
          { ...baseItem, id: 'i1', carton_tag: 'SHX-00001', description: 'First item' },
          { ...baseItem, id: 'i2', carton_tag: 'SHX-00002', description: 'Second item' },
        ],
      }),
    )
    renderPage('china_office_staff', 'staff-1')
    await userEvent.click(await screen.findByText('Revise and resubmit'))

    expect(screen.getByText('SHX-00001')).toBeInTheDocument()
    expect(screen.getByText('SHX-00002')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove item 1' }))

    // Remaining row must keep SHX-00002, not inherit SHX-00001 from index 0
    expect(screen.queryByText('SHX-00001')).not.toBeInTheDocument()
    expect(screen.getByText('SHX-00002')).toBeInTheDocument()
  })
})
