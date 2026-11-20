import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { claimsApi } from '../../api/claims'
import { ClaimDetail } from './ClaimDetail'

vi.mock('../../api/claims', () => ({
  claimsApi: { list: vi.fn(), get: vi.fn(), file: vi.fn(), startInspection: vi.fn(), resolve: vi.fn() },
  missingItemsApi: { list: vi.fn(), get: vi.fn(), update: vi.fn() },
  seizedItemsApi: { list: vi.fn(), get: vi.fn(), update: vi.fn() },
  presignedUploadApi: { getUrl: vi.fn() },
}))

function makeCtx(role = 'nigeria_office_staff'): SessionContextValue {
  const session: Session = {
    tenantId: 't1', userId: 'u1', name: null, role: role as Session['role'], roles: [role as Session['role']],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null,
    readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
  return { session, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }
}

const CLAIM_STUB = {
  id: 'c1',
  reference: 'DC-20260601-001',
  status: 'filed' as const,
  container_id: null,
  container_number: null,
  customer_id: null,
  customer_name: null,
  description: 'Water damage to carton',
  inspection_method: null,
  cartons_affected: ['C001', 'C002'],
  upload_urls: null,
  created_at: '2026-06-15T10:00:00Z',
}

function renderPage(role = 'nigeria_office_staff', routeState: object | null = { claim: CLAIM_STUB }) {
  render(
    withQuery(
      <MemoryRouter initialEntries={[{ pathname: '/claims/c1', state: routeState ?? undefined }]}>
        <SessionContext.Provider value={makeCtx(role)}>
          <Routes><Route path="/claims/:id" element={<ClaimDetail />} /></Routes>
        </SessionContext.Provider>
      </MemoryRouter>,
    ),
  )
}

beforeEach(() => {
  vi.mocked(claimsApi.get).mockReset()
  vi.mocked(claimsApi.startInspection).mockReset()
  vi.mocked(claimsApi.resolve).mockReset()
})

describe('ClaimDetail', () => {
  it('renders claim from router state without API fetch', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Damage claim DC-20260601-001' })).toBeInTheDocument())
    expect(screen.queryByText('c1')).toBeNull() // titled by its reference, never its database id (FD-17)
    expect(screen.getByText('C001')).toBeInTheDocument()
    expect(claimsApi.get).not.toHaveBeenCalled()
  })

  it('falls back to API fetch when no router state', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue(CLAIM_STUB)
    renderPage('nigeria_office_staff', null)
    await waitFor(() => expect(claimsApi.get).toHaveBeenCalledWith('c1'))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Damage claim DC-20260601-001' })).toBeInTheDocument())
  })

  it('shows Start inspection button for nigeria on filed claim', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Start inspection' })).toBeInTheDocument())
  })

  it('hides Start inspection for tenant_admin', async () => {
    renderPage('tenant_admin')
    await screen.findByRole('heading', { name: 'Damage claim DC-20260601-001' })
    expect(screen.queryByRole('button', { name: 'Start inspection' })).not.toBeInTheDocument()
  })

  it('opens inspection modal and submits', async () => {
    vi.mocked(claimsApi.startInspection).mockResolvedValue({ ...CLAIM_STUB, status: 'under_inspection' })
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Start inspection' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Start inspection' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/Inspection method/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Start inspection' }))
    await waitFor(() => expect(claimsApi.startInspection).toHaveBeenCalledWith('c1', { inspection_method: 'delegate_visit' }))
  })

  it('tells staff the customer will read the reason when the claim is closed without a payout, and not otherwise', async () => {
    renderPage('nigeria_office_staff', { claim: { ...CLAIM_STUB, status: 'pending_resolution' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Resolve claim' }))
    const dialog = screen.getByRole('dialog')
    // "No action" is the default pick: the reason goes to the customer, and nothing can be sent without one.
    expect(within(dialog).getByText(/Reason \(the customer will see this\)/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Resolve claim' })).toBeDisabled()

    await userEvent.click(within(dialog).getByText('Refund'))
    expect(within(dialog).getByText(/Reason \(internal, not shown to the customer\)/)).toBeInTheDocument()
    expect(within(dialog).queryByText(/the customer will see this/)).toBeNull()
  })

  it('shows no action buttons on terminal claim', async () => {
    renderPage('nigeria_office_staff', { claim: { ...CLAIM_STUB, status: 'resolved' } })
    // 'Resolved' appears as hero badge + stepper step — use getAllByText
    await waitFor(() => expect(screen.getAllByText('Resolved').length).toBeGreaterThanOrEqual(1))
    expect(screen.queryByRole('button', { name: 'Start inspection' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resolve claim' })).not.toBeInTheDocument()
  })
})
