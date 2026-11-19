/**
 * 3.2 / audit gap B4 — staff list enrichment: role filter chips with counts,
 * search, and the Created column. Customer-role rows are always excluded.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usersApi, type TenantUser } from '../../api/tenantManagement'
import { StaffUserList } from './StaffUserList'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, usersApi: { ...original.usersApi, list: vi.fn(), create: vi.fn() } }
})

function user(overrides: Partial<TenantUser>): TenantUser {
  return {
    id: 'u1', tenant_id: 't1', email: 'amara@acme.com', full_name: 'Amara Okafor',
    role: 'tenant_admin', roles: ['tenant_admin'], status: 'active', locale: null, created_at: '2026-01-14T00:00:00Z',
    ...overrides,
  }
}

const STAFF = [
  user({ id: 'u1', full_name: 'Amara Okafor', role: 'tenant_admin' }),
  user({ id: 'u2', full_name: 'Kwame Asante', email: 'kwame@acme.com', role: 'china_office_staff' }),
  user({ id: 'u3', full_name: 'Ifeoma Uche', email: 'ifeoma@acme.com', role: 'nigeria_office_staff' }),
  user({ id: 'u4', full_name: 'A Customer', email: 'cust@acme.com', role: 'customer' }),
]

function renderPage(state?: Record<string, unknown>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: '/admin/users', state: state ?? null }]}>
        <Routes>
          <Route path="/admin/users" element={<StaffUserList />} />
          <Route path="/admin/users/:id" element={<div>Staff profile</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('StaffUserList (B4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(usersApi.list).mockResolvedValue(STAFF)
  })

  it('excludes customers, shows the Created column and role chips', async () => {
    renderPage()
    expect(await screen.findByText('Amara Okafor')).toBeInTheDocument()
    expect(screen.queryByText('A Customer')).toBeNull()
    expect(screen.getAllByText('14 Jan 2026').length).toBe(3)
    // "All 3" chip (customers excluded from the count)
    const allChip = screen.getAllByText('All').find((el) => el.closest('button'))!
    expect(allChip.closest('button')).toHaveTextContent('3')
  })

  it('filters by role chip', async () => {
    renderPage()
    await screen.findByText('Amara Okafor')
    const chinaChip = screen.getAllByText('China office').find((el) => el.closest('button'))!
    await userEvent.click(chinaChip)
    expect(screen.getByText('Kwame Asante')).toBeInTheDocument()
    expect(screen.queryByText('Amara Okafor')).toBeNull()
  })

  it('searches by name', async () => {
    renderPage()
    await screen.findByText('Amara Okafor')
    await userEvent.type(screen.getByPlaceholderText(/search by name/i), 'ifeoma')
    expect(screen.getByText('Ifeoma Uche')).toBeInTheDocument()
    expect(screen.queryByText('Amara Okafor')).toBeNull()
  })

  // §3.1 dashboard quick action deep-link
  it('auto-opens the invite modal when navigated with openInvite state', async () => {
    renderPage({ openInvite: true })
    expect(await screen.findByLabelText(/full name/i)).toBeInTheDocument()
  })

  it('opens a staff profile on view', async () => {
    renderPage()
    await screen.findByText('Amara Okafor')
    const row = screen.getByText('Amara Okafor').closest('tr')!
    await userEvent.click(within(row).getByText('View'))
    expect(await screen.findByText('Staff profile')).toBeInTheDocument()
  })

  // Breaking change (2026-07-20): role -> roles + primary_role. The invite
  // modal defaults to a single pre-checked role, and checking a second role
  // lets the invite go out with more than one assigned. Queries are scoped to
  // the dialog since the filter chips behind it render the same role labels.
  it('invites with a single default role checked (nigeria_office_staff, primary)', async () => {
    vi.mocked(usersApi.create).mockResolvedValue(user({ id: 'u5', full_name: 'New Hire' }))
    renderPage({ openInvite: true })
    const dialog = within(await screen.findByRole('dialog'))
    await userEvent.type(dialog.getByLabelText(/email/i), 'new@acme.com')
    await userEvent.type(dialog.getByLabelText(/full name/i), 'New Hire')

    await userEvent.click(dialog.getByText('Send invite'))

    expect(usersApi.create).toHaveBeenCalledWith({
      email: 'new@acme.com',
      full_name: 'New Hire',
      roles: ['nigeria_office_staff'],
      primary_role: 'nigeria_office_staff',
    })
  })

  it('invites with more than one role checked, marking one as primary', async () => {
    vi.mocked(usersApi.create).mockResolvedValue(user({ id: 'u6', full_name: 'Multi Role' }))
    renderPage({ openInvite: true })
    const dialog = within(await screen.findByRole('dialog'))
    await userEvent.type(dialog.getByLabelText(/email/i), 'multi@acme.com')
    await userEvent.type(dialog.getByLabelText(/full name/i), 'Multi Role')

    // Nigeria (default) is already checked; also check Warehouse.
    await userEvent.click(dialog.getByText('Warehouse'))
    await userEvent.click(dialog.getByText('Send invite'))

    expect(usersApi.create).toHaveBeenCalledWith({
      email: 'multi@acme.com',
      full_name: 'Multi Role',
      roles: ['nigeria_office_staff', 'warehouse_attendant'],
      primary_role: 'nigeria_office_staff',
    })
  })

  it('unchecking the only role disables the invite submit button', async () => {
    renderPage({ openInvite: true })
    const dialog = within(await screen.findByRole('dialog'))
    await dialog.findByLabelText(/email/i)

    await userEvent.click(dialog.getByText('Nigeria office'))

    expect(dialog.getByText('Send invite').closest('button')).toBeDisabled()
  })
})
