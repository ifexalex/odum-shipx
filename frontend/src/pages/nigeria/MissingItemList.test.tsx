import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { missingItemsApi } from '../../api/claims'
import { MissingItemList } from './MissingItemList'

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

const ITEM_STUB = {
  id: 'm1',
  manifest_id: 'mf1',
  customer_id: 'cust1',
  carton_tags: ['C005', 'C006'],
  description: 'Electronic components',
  status: 'reported' as const,
  created_at: '2026-06-01T10:00:00Z',
}

beforeEach(() => { vi.mocked(missingItemsApi.list).mockReset() })

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('MissingItemList', () => {
  it('renders missing items', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('Electronic components')).toBeInTheDocument())
    expect(screen.getByText('C005, C006')).toBeInTheDocument()
  })

  it('shows Update button for nigeria on non-resolved items', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument())
  })

  it('hides Update button for tenant_admin', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx('tenant_admin')}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('Electronic components')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Update' })).not.toBeInTheDocument()
  })

  it('shows empty state', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText(/No missing items/)).toBeInTheDocument())
  })

  describe('compensation when an item is confirmed lost', () => {
    async function openUpdateModal() {
      vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
      vi.mocked(missingItemsApi.update).mockReset()
      vi.mocked(missingItemsApi.update).mockResolvedValue({ ...ITEM_STUB, status: 'confirmed_lost' })
      render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
      await userEvent.click(await screen.findByRole('button', { name: 'Update' }))
      return screen.getByRole('dialog')
    }

    it('offers a compensation amount only once the status is confirmed lost', async () => {
      await openUpdateModal()
      expect(screen.queryByLabelText(/Compensation/)).not.toBeInTheDocument()

      await userEvent.selectOptions(screen.getByRole('combobox'), 'confirmed_lost')
      expect(screen.getByLabelText(/Compensation/)).toBeInTheDocument()

      await userEvent.selectOptions(screen.getByRole('combobox'), 'resolved')
      expect(screen.queryByLabelText(/Compensation/)).not.toBeInTheDocument()
    })

    it('sends the amount with the status', async () => {
      await openUpdateModal()
      await userEvent.selectOptions(screen.getByRole('combobox'), 'confirmed_lost')
      await userEvent.type(screen.getByLabelText(/Compensation/), '25000')
      await userEvent.click(screen.getByRole('button', { name: 'Save update' }))

      await waitFor(() =>
        expect(missingItemsApi.update).toHaveBeenCalledWith('m1', { status: 'confirmed_lost', refund_amount_ngn: '25000' }),
      )
    })

    it('confirms the loss without compensation when the amount is left blank', async () => {
      await openUpdateModal()
      await userEvent.selectOptions(screen.getByRole('combobox'), 'confirmed_lost')
      await userEvent.click(screen.getByRole('button', { name: 'Save update' }))

      await waitFor(() => expect(missingItemsApi.update).toHaveBeenCalledWith('m1', { status: 'confirmed_lost' }))
    })

    it('does not send an amount typed before switching to another status', async () => {
      await openUpdateModal()
      await userEvent.selectOptions(screen.getByRole('combobox'), 'confirmed_lost')
      await userEvent.type(screen.getByLabelText(/Compensation/), '25000')
      await userEvent.selectOptions(screen.getByRole('combobox'), 'resolved')
      await userEvent.click(screen.getByRole('button', { name: 'Save update' }))

      await waitFor(() => expect(missingItemsApi.update).toHaveBeenCalledWith('m1', { status: 'resolved' }))
    })

    it('blocks saving an amount that is not greater than zero', async () => {
      await openUpdateModal()
      await userEvent.selectOptions(screen.getByRole('combobox'), 'confirmed_lost')
      await userEvent.type(screen.getByLabelText(/Compensation/), '0')

      expect(screen.getByText('Enter an amount greater than 0.')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Save update' })).toBeDisabled()
    })
  })
})
