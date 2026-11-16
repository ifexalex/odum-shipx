import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { staffNotificationsApi } from '../api/staffNotifications'
import { StaffLayout } from './StaffLayout'

vi.mock('../api/staffNotifications', () => ({
  staffNotificationsApi: {
    list: vi.fn(),
    unreadCount: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
    getBanner: vi.fn().mockResolvedValue(null),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

function makeSession(role: Session['role'], roles: Session['role'][] = [role]): Session {
  return {
    tenantId: 't1',
    userId: 'u1',
    name: null,
    role,
    roles,
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
}

function makeContextValue(overrides: Partial<SessionContextValue>): SessionContextValue {
  return {
    session: null,
    status: 'unauthenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
    ...overrides,
  }
}

// StaffLayout mounts QuotaWarningBanner (useQuery) — provide the client the
// app root always provides in production.
function renderLayout(value: SessionContextValue, path: string, children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>
          <StaffLayout>{children}</StaffLayout>
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

describe('StaffLayout', () => {
  it('renders the sidebar, topbar, and the children content', () => {
    renderLayout(
      makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    expect(screen.getByText('Dashboard content')).toBeInTheDocument()
    // Sidebar nav item for the current role.
    expect(screen.getByText('Users')).toBeInTheDocument()
  })

  it('shows a breadcrumb + TopBar title on a list route', () => {
    renderLayout(
      makeContextValue({ session: makeSession('china_office_staff'), status: 'authenticated' }),
      '/containers',
      <div>Containers content</div>,
    )
    // Breadcrumb (Operations / Containers) + TopBar h1 + sidebar nav all say "Containers"
    expect(screen.getAllByText('Operations').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Containers').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByRole('heading', { name: 'Containers' })).toBeInTheDocument()
  })

  it('suppresses the TopBar title on a form (…/new) route so the body PageHeader is the only heading', () => {
    renderLayout(
      makeContextValue({ session: makeSession('china_office_staff'), status: 'authenticated' }),
      '/containers/new',
      <div>Create form body</div>,
    )
    // No TopBar <h1> title on form routes (title is blanked); breadcrumb still present.
    expect(screen.queryByRole('heading', { name: 'Create container' })).toBeNull()
    expect(screen.getByText('Create form body')).toBeInTheDocument()
  })

  it('renders nothing when there is no session', () => {
    const { container } = renderLayout(makeContextValue({}), '/dashboard', <div>Dashboard content</div>)
    expect(container).toBeEmptyDOMElement()
  })

  it('switching the active role navigates to that role\'s home path, not just updating the sidebar', () => {
    const setActiveRole = vi.fn()
    renderLayout(
      makeContextValue({
        session: makeSession('nigeria_office_staff', ['nigeria_office_staff', 'warehouse_attendant']),
        status: 'authenticated',
        setActiveRole,
      }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    // Regression test: previously setActiveRole flipped session.role (updating
    // nav/breadcrumb) but never navigated, so the page stayed mounted at the
    // OLD role's route until the user separately clicked a nav link.
    fireEvent.change(screen.getByRole('combobox', { name: 'Active role' }), { target: { value: 'warehouse_attendant' } })
    expect(setActiveRole).toHaveBeenCalledWith('warehouse_attendant')
    expect(mockNavigate).toHaveBeenCalledWith('/warehouse')
  })

  it('re-derives the active role from the URL when session.role disagrees with the current page (e.g. after a reload)', () => {
    const setActiveRole = vi.fn()
    // Simulates: user switched to Warehouse, then reloaded. The reload rebuilds
    // session.role from the JWT's primary role (nigeria_office_staff) — never
    // persisted client-side — but the URL still points at /warehouse.
    renderLayout(
      makeContextValue({
        session: makeSession('nigeria_office_staff', ['nigeria_office_staff', 'warehouse_attendant']),
        status: 'authenticated',
        setActiveRole,
      }),
      '/warehouse',
      <div>Warehouse content</div>,
    )
    expect(setActiveRole).toHaveBeenCalledWith('warehouse_attendant')
  })

  it('shows the staff notification unread count on the TopBar bell', async () => {
    vi.mocked(staffNotificationsApi.unreadCount).mockReset().mockResolvedValue({ unread_count: 3 })
    renderLayout(
      makeContextValue({ session: makeSession('nigeria_office_staff'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    expect(await screen.findByText('3')).toBeInTheDocument()
  })

  it('opens the notification panel when the bell is clicked', async () => {
    vi.mocked(staffNotificationsApi.unreadCount).mockReset().mockResolvedValue({ unread_count: 1 })
    vi.mocked(staffNotificationsApi.list).mockReset().mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderLayout(
      makeContextValue({ session: makeSession('nigeria_office_staff'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    fireEvent.click(screen.getByRole('button', { name: /notifications/i }))
    expect(await screen.findByRole('dialog', { name: /notifications/i })).toBeInTheDocument()
  })

  it('does not fetch or show an unread count for platform_admin (bare platform shell, no tenant context)', () => {
    vi.mocked(staffNotificationsApi.unreadCount).mockReset()
    renderLayout(
      makeContextValue({ session: makeSession('platform_admin'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    // The bell icon itself is always in the DOM (TopBar renders it
    // unconditionally) — what must be suppressed for a bare platform admin
    // is the badge count and the API call behind it, same gate as branding.
    expect(staffNotificationsApi.unreadCount).not.toHaveBeenCalled()
  })

  it('clicking the bell does nothing for platform_admin — no panel, no list fetch', () => {
    vi.mocked(staffNotificationsApi.list).mockReset()
    renderLayout(
      makeContextValue({ session: makeSession('platform_admin'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    fireEvent.click(screen.getByRole('button', { name: /notifications/i }))
    expect(screen.queryByRole('dialog', { name: /notifications/i })).toBeNull()
    expect(staffNotificationsApi.list).not.toHaveBeenCalled()
  })

  it('does not flip the active role for a route shared across roles (no false-positive correction)', () => {
    const setActiveRole = vi.fn()
    // /dashboard belongs to nigeria_office_staff's own nav, so it should stay
    // the active role even though the user also holds warehouse_attendant.
    renderLayout(
      makeContextValue({
        session: makeSession('nigeria_office_staff', ['nigeria_office_staff', 'warehouse_attendant']),
        status: 'authenticated',
        setActiveRole,
      }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    expect(setActiveRole).not.toHaveBeenCalled()
  })

  it('shows the active announcement as a page banner', async () => {
    vi.mocked(staffNotificationsApi.getBanner).mockReset().mockResolvedValue({
      id: 'ann1',
      tenant_id: 't1',
      target_role: 'nigeria_office_staff',
      target_user_id: null,
      event_type: 'announcement',
      entity_type: 'announcement',
      entity_id: null,
      title: 'Office closed for the holidays',
      body: 'We resume Monday.',
      is_read: false,
      created_at: new Date().toISOString(),
    })
    renderLayout(
      makeContextValue({ session: makeSession('nigeria_office_staff'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    expect(await screen.findByText('Office closed for the holidays')).toBeInTheDocument()
    expect(screen.getByText('We resume Monday.')).toBeInTheDocument()
  })

  it('shows no banner when nothing is active', async () => {
    vi.mocked(staffNotificationsApi.getBanner).mockReset().mockResolvedValue(null)
    renderLayout(
      makeContextValue({ session: makeSession('nigeria_office_staff'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    await screen.findByText('Dashboard content')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('does not fetch the banner for platform_admin (bare platform shell, no tenant context)', () => {
    vi.mocked(staffNotificationsApi.getBanner).mockReset()
    renderLayout(
      makeContextValue({ session: makeSession('platform_admin'), status: 'authenticated' }),
      '/dashboard',
      <div>Dashboard content</div>,
    )
    expect(staffNotificationsApi.getBanner).not.toHaveBeenCalled()
  })
})

describe('StaffLayout global search (UX-05)', () => {
  const as = (role: Parameters<typeof makeSession>[0]) =>
    makeContextValue({ session: makeSession(role), status: 'authenticated' })

  it('shows the global search box on every page, not just list pages', () => {
    renderLayout(as('tenant_admin'), '/dashboard', <div>Dashboard content</div>)
    expect(screen.getByRole('combobox', { name: 'Search containers, invoices, customers…' })).toBeInTheDocument()
  })

  it('names only what the role can find', () => {
    renderLayout(as('warehouse_attendant'), '/warehouse', <div>Warehouse</div>)
    expect(screen.getByRole('combobox', { name: 'Search release notes…' })).toBeInTheDocument()
  })

  it('offers no search to a platform admin, who spans tenants and is refused by the server', () => {
    renderLayout(as('platform_admin'), '/platform/dashboard', <div>Platform</div>)
    expect(screen.queryByRole('combobox')).toBeNull()
  })
})
