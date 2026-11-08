/**
 * Multi-role staff support (2026-07-20) — the "Roles" edit flow: a checkbox
 * per assignable role plus a radio marking which checked role is primary,
 * replacing the old single-role <select>. PATCH /v1/tenant/users/{id} now
 * sends { roles, primary_role } instead of { role }.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { usersApi, type TenantUser } from '../../api/tenantManagement'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { StaffUserDetail } from './StaffUserDetail'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    usersApi: { ...original.usersApi, get: vi.fn(), update: vi.fn() },
    configApi: { ...original.configApi, activity: vi.fn().mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }) },
  }
})

function makeSession(): Session {
  return {
    tenantId: 't1', userId: 'u1', name: 'Admin', role: 'tenant_admin', roles: ['tenant_admin'],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null,
    readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
}

function makeContextValue(): SessionContextValue {
  return {
    session: makeSession(),
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(),
    setActiveRole: vi.fn(),
  }
}

function user(overrides: Partial<TenantUser> = {}): TenantUser {
  return {
    id: 'u1',
    tenant_id: 't1',
    email: 'amaka@acme.com',
    full_name: 'Amaka Nwachukwu',
    role: 'nigeria_office_staff',
    roles: ['nigeria_office_staff', 'warehouse_attendant'],
    status: 'active',
    locale: 'en',
    created_at: '2026-07-01T00:00:00Z',
    ...overrides,
  }
}

function renderPage(stateUser?: TenantUser) {
  return render(
    withQuery(
    <SessionContext.Provider value={makeContextValue()}>
      <MemoryRouter initialEntries={[{ pathname: '/admin/users/u1', state: stateUser ? { user: stateUser } : null }]}>
        <Routes>
          <Route path="/admin/users/:id" element={<StaffUserDetail />} />
          <Route path="/admin/users" element={<div>Staff list</div>} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
    ),
  )
}

describe('StaffUserDetail — multi-role editing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows a badge for every assigned role, marking the primary one', async () => {
    renderPage(user())

    // Exact-textContent match on the badge itself, scoped to avoid matching
    // an ancestor whose concatenated text happens to also contain both substrings.
    expect(
      await screen.findByText((_, el) => el?.textContent === 'nigeria office staff · primary'),
    ).toBeInTheDocument()
    expect(screen.getByText('warehouse attendant')).toBeInTheDocument()
  })

  // RoleCheckboxList renders ROLE_OPTIONS in this fixed order — index into
  // getAllByRole('checkbox')/getAllByRole('radio') rather than getByText,
  // since an assigned-but-non-primary role's summary badge (e.g. plain
  // "warehouse attendant", no " · primary" suffix) renders the exact same
  // text as its checkbox-list label and would otherwise collide.
  const ROLE_INDEX = { tenant_admin: 0, china_office_staff: 1, nigeria_office_staff: 2, warehouse_attendant: 3 }

  it('opens the role checkbox editor on Change, pre-selecting the current roles and primary', async () => {
    renderPage(user())
    await userEvent.click(await screen.findByText('Change'))

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[ROLE_INDEX.nigeria_office_staff]).toHaveAttribute('aria-checked', 'true')
    expect(checkboxes[ROLE_INDEX.warehouse_attendant]).toHaveAttribute('aria-checked', 'true')
    expect(checkboxes[ROLE_INDEX.tenant_admin]).toHaveAttribute('aria-checked', 'false')
    expect(checkboxes[ROLE_INDEX.china_office_staff]).toHaveAttribute('aria-checked', 'false')
  })

  it('saves with roles + primary_role (not the old singular role field)', async () => {
    vi.mocked(usersApi.update).mockResolvedValue(
      user({ role: 'warehouse_attendant', roles: ['warehouse_attendant'] }),
    )
    renderPage(user())
    await userEvent.click(await screen.findByText('Change'))

    // Uncheck nigeria_office_staff — warehouse_attendant becomes the only
    // (and therefore primary) role, per RoleCheckboxList's auto-primary rule.
    await userEvent.click(screen.getAllByRole('checkbox')[ROLE_INDEX.nigeria_office_staff]!)
    await userEvent.click(screen.getByText('Save'))

    expect(usersApi.update).toHaveBeenCalledWith('u1', {
      roles: ['warehouse_attendant'],
      primary_role: 'warehouse_attendant',
    })
  })

  it('marking a non-default role primary via its radio sends that as primary_role', async () => {
    vi.mocked(usersApi.update).mockResolvedValue(user())
    renderPage(user())
    await userEvent.click(await screen.findByText('Change'))

    // warehouse_attendant is already checked (non-primary) — its radio is
    // rendered; clicking it re-marks it primary without changing selection.
    const warehouseRow = screen.getAllByRole('checkbox')[ROLE_INDEX.warehouse_attendant]!.closest('div')!
    await userEvent.click(within(warehouseRow).getByRole('radio'))
    await userEvent.click(screen.getByText('Save'))

    expect(usersApi.update).toHaveBeenCalledWith('u1', {
      roles: ['nigeria_office_staff', 'warehouse_attendant'],
      primary_role: 'warehouse_attendant',
    })
  })

  it('disables Save when every role is unchecked', async () => {
    renderPage(user({ roles: ['warehouse_attendant'] }))
    await userEvent.click(await screen.findByText('Change'))

    await userEvent.click(screen.getAllByRole('checkbox')[ROLE_INDEX.warehouse_attendant]!)

    expect(screen.getByText('Save').closest('button')).toBeDisabled()
  })

  it('cancel discards edits without calling the API', async () => {
    renderPage(user())
    await userEvent.click(await screen.findByText('Change'))
    await userEvent.click(screen.getAllByRole('checkbox')[ROLE_INDEX.nigeria_office_staff]!)

    await userEvent.click(screen.getByText('Cancel'))

    expect(usersApi.update).not.toHaveBeenCalled()
    // Back to the read view — original badges restored, Change button back.
    expect(await screen.findByText('Change')).toBeInTheDocument()
  })
})
