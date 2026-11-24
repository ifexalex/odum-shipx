import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
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

describe('China office view of missing items (UX-08)', () => {
  const page = { data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } }

  function renderAs(role: string) {
    vi.mocked(missingItemsApi.list).mockResolvedValue(page)
    vi.mocked(missingItemsApi.update).mockReset()
    vi.mocked(missingItemsApi.update).mockResolvedValue({ ...ITEM_STUB, status: 'investigating' })
    return render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx(role)}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
  }

  async function openUpdate(role = 'china_office_staff') {
    renderAs(role)
    await userEvent.click(await screen.findByRole('button', { name: 'Update' }))
    return screen.findByRole('dialog', { name: 'Update missing item' })
  }

  it('lists the items and offers an Update on one that is still open', async () => {
    renderAs('china_office_staff')
    expect(await screen.findByText('Electronic components')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument()
  })

  it('says what this screen is for them', async () => {
    renderAs('china_office_staff')
    await screen.findByText('Electronic components')
    // the subtitle is placed in the top bar by the layout; the dialog carries the same guidance
    const dialog = await openUpdate()
    expect(within(dialog).getByText(/supply and loading check/i)).toBeInTheDocument()
  })

  it('offers only the investigation statuses, never a decision', async () => {
    const dialog = await openUpdate()
    const options = within(dialog).getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(['Investigating', 'Found, shipping'])
  })

  it('has no compensation field, even if the status is changed', async () => {
    const dialog = await openUpdate()
    await userEvent.selectOptions(within(dialog).getByRole('combobox'), 'found_and_shipping')
    expect(within(dialog).queryByLabelText(/Compensation/)).toBeNull()
    expect(within(dialog).queryByText(/Compensation \(₦\)/)).toBeNull()
  })

  it('records the investigation result and notes, and sends no amount', async () => {
    const dialog = await openUpdate()
    await userEvent.type(within(dialog).getByPlaceholderText(/Add any notes/), 'Loaded 12 cartons, 3 not on the dock')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save update' }))
    await waitFor(() => expect(missingItemsApi.update).toHaveBeenCalledTimes(1))
    const [id, body] = vi.mocked(missingItemsApi.update).mock.calls[0]!
    expect(id).toBe('m1')
    expect(body).toEqual({ status: 'investigating', notes: 'Loaded 12 cartons, 3 not on the dock' })
    expect(body).not.toHaveProperty('refund_amount_ngn')
  })

  it('offers no Update on an item that has already been decided', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ ...page, data: [{ ...ITEM_STUB, status: 'confirmed_lost' as const }] })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx('china_office_staff')}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await screen.findByText('Electronic components')
    expect(screen.queryByRole('button', { name: 'Update' })).toBeNull()
  })

  it('leaves the Nigeria office every status and the compensation field', async () => {
    const dialog = await openUpdate('nigeria_office_staff')
    expect(within(dialog).getAllByRole('option')).toHaveLength(5)
    await userEvent.selectOptions(within(dialog).getByRole('combobox'), 'confirmed_lost')
    expect(within(dialog).getByText(/Compensation \(₦\)/)).toBeInTheDocument()
  })
})

