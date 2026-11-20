import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { disputeApi, type DisputeDetail as DisputeDetailData } from '../../api/billing'
import { ApiError } from '../../api/client'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { DisputeList } from '../nigeria/DisputeList'
import { DisputeDetail } from './DisputeDetail'

vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return { ...original, disputeApi: { list: vi.fn(), get: vi.fn(), resolve: vi.fn(), acknowledge: vi.fn(), reject: vi.fn() } }
})

const DETAIL: DisputeDetailData = {
  id: 'd1', billing_id: 'b1', original_cbm: '2.000', corrected_cbm: null, status: 'escalated_china',
  submitted_at: '2026-11-01T10:00:00Z', customer_name: 'Ngozi Okonkwo', container_number: 'MSKU1234567',
  reason: 'The cartons are smaller than invoiced', customer_measured_cbm: '1.800', billed_cbm: '2.000', resolution_notes: null,
  lines: [
    { reference: 'PL-1', carton_tag: 'T1', description: 'Shoes', quantity: 4, package_unit: 'ctn', cbm: '0.500',
      length_cm: '50', width_cm: '40', height_cm: '25', weight_kg: '12' },
    { reference: 'PL-1', carton_tag: 'T2', description: 'Bags', quantity: 2, package_unit: null, cbm: '1.500',
      length_cm: null, width_cm: null, height_cm: null, weight_kg: null },
  ],
}

function china(): SessionContextValue {
  const session: Session = {
    tenantId: 't1', userId: 'u1', name: null, role: 'china_office_staff', roles: ['china_office_staff'],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null, readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
  return { session, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SessionContext.Provider value={china()}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/billing/disputes" element={<DisputeList />} />
            <Route path="/billing/disputes/:id" element={<DisputeDetail />} />
            <Route path="/billing/:id" element={<div>THE INVOICE PAGE</div>} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

describe('China staff and a CBM dispute (UX-01)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('can open an escalated dispute from the list, read it, and resolve it', async () => {
    vi.mocked(disputeApi.list).mockResolvedValue({
      data: [{ id: 'd1', billing_id: 'b1', original_cbm: '2.000', corrected_cbm: null, status: 'escalated_china', submitted_at: '2026-11-01T10:00:00Z' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(disputeApi.get).mockResolvedValue(DETAIL)
    vi.mocked(disputeApi.resolve).mockResolvedValue({ ...DETAIL, status: 'resolved_adjusted' })
    renderAt('/billing/disputes')

    // From the list: opening the row goes to the dispute screen, not the invoice they cannot open.
    const disputeRow = (await screen.findByText('2.000')).closest('tr')!
    await userEvent.click(within(disputeRow).getAllByRole('button')[0]!)
    expect(await screen.findByRole('heading', { name: 'CBM dispute on MSKU1234567' })).toBeInTheDocument()
    expect(screen.queryByText('THE INVOICE PAGE')).toBeNull()

    // What they need to judge the measurement.
    expect(screen.getByText('The cartons are smaller than invoiced', { exact: false })).toBeInTheDocument()
    expect(screen.getAllByText('2.000').length).toBeGreaterThan(0)
    expect(screen.getByText('1.800')).toBeInTheDocument()
    expect(screen.getByText('50 × 40 × 25')).toBeInTheDocument()
    expect(screen.getByText(/2 lines · 2\.000 CBM/)).toBeInTheDocument()

    // Resolve with a corrected CBM.
    await userEvent.click(screen.getByRole('button', { name: 'Adjust CBM' }))
    await userEvent.type(screen.getByLabelText(/Corrected CBM/), '1.8')
    await userEvent.type(screen.getByLabelText(/Resolution notes/), 'Re-measured: smaller')
    await userEvent.click(screen.getByRole('button', { name: 'Resolve dispute' }))

    await waitFor(() =>
      expect(disputeApi.resolve).toHaveBeenCalledWith('d1', {
        status: 'resolved_adjusted', corrected_cbm: '1.8', resolution_notes: 'Re-measured: smaller',
      }),
    )
  })

  it('cannot resolve without notes, or an adjustment without a corrected CBM', async () => {
    vi.mocked(disputeApi.get).mockResolvedValue(DETAIL)
    renderAt('/billing/disputes/d1')
    await screen.findByRole('heading', { name: 'CBM dispute on MSKU1234567' })

    const resolve = screen.getByRole('button', { name: 'Resolve dispute' })
    expect(resolve).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Resolution notes/), 'Looks right')
    expect(resolve).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Adjust CBM' }))
    expect(resolve).toBeDisabled()
  })

  it('resolves with no change', async () => {
    vi.mocked(disputeApi.get).mockResolvedValue(DETAIL)
    vi.mocked(disputeApi.resolve).mockResolvedValue({ ...DETAIL, status: 'resolved_no_change' })
    renderAt('/billing/disputes/d1')
    await screen.findByRole('heading', { name: 'CBM dispute on MSKU1234567' })

    await userEvent.type(screen.getByLabelText(/Resolution notes/), 'Billed CBM is right')
    await userEvent.click(screen.getByRole('button', { name: 'Resolve dispute' }))
    await waitFor(() =>
      expect(disputeApi.resolve).toHaveBeenCalledWith('d1', { status: 'resolved_no_change', resolution_notes: 'Billed CBM is right' }),
    )
  })

  it('shows the server message when resolving fails', async () => {
    vi.mocked(disputeApi.get).mockResolvedValue(DETAIL)
    vi.mocked(disputeApi.resolve).mockRejectedValue(
      new ApiError({ type: 'x', title: 'x', status: 409, detail: 'Dispute was already resolved.', error_code: 'ILLEGAL_TRANSITION' }, null),
    )
    renderAt('/billing/disputes/d1')
    await screen.findByRole('heading', { name: 'CBM dispute on MSKU1234567' })
    await userEvent.type(screen.getByLabelText(/Resolution notes/), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Resolve dispute' }))
    expect(await screen.findByText('Dispute was already resolved.')).toBeInTheDocument()
  })

  it('shows a resolved dispute read-only', async () => {
    vi.mocked(disputeApi.get).mockResolvedValue({ ...DETAIL, status: 'resolved_no_change', resolution_notes: 'Checked on site' })
    renderAt('/billing/disputes/d1')
    expect(await screen.findByText('This dispute is resolved')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resolve dispute' })).toBeNull()
  })

  it('says so when there are no lines, and shows no money', async () => {
    vi.mocked(disputeApi.get).mockResolvedValue({ ...DETAIL, lines: [] })
    renderAt('/billing/disputes/d1')
    expect(await screen.findByText(/No approved packing-list lines/)).toBeInTheDocument()
    expect(screen.queryByText(/₦|NGN|\$/)).toBeNull()
  })

  it('reports a dispute that is not found', async () => {
    vi.mocked(disputeApi.get).mockRejectedValue(
      new ApiError({ type: 'x', title: 'x', status: 404, detail: 'gone', error_code: 'RESOURCE_NOT_FOUND' }, null),
    )
    renderAt('/billing/disputes/zzz')
    expect(await screen.findByText('Dispute not found.')).toBeInTheDocument()
  })
})
