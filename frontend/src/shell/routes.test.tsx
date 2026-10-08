import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { AppRoutes } from './routes'

function makeSession(role: Session['role']): Session {
  return {
    tenantId: role === 'platform_admin' ? 'PLATFORM' : 't1',
    userId: 'u1',
    name: null,
    role,
    roles: [role],
    isPlatformAdmin: role === 'platform_admin',
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

function renderAt(value: SessionContextValue, path: string) {
  // StaffLayout mounts QuotaWarningBanner (useQuery) — provide the client the
  // app root always provides in production.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

describe('AppRoutes', () => {
  it('renders the real LoginScreen at the public /login route with no guard', () => {
    renderAt(makeContextValue({}), '/login')
    expect(screen.getByText('Sign in to ShipX')).toBeInTheDocument()
  })

  it('shows the public marketing landing page at / when signed out', () => {
    renderAt(makeContextValue({}), '/')
    expect(screen.getByRole('heading', { name: /Run your entire cargo operation/ })).toBeInTheDocument()
  })

  it("redirects / to the visitor's own home when signed in", () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/')
    expect(screen.getAllByText('Dashboard').length).toBeGreaterThan(0) // real Dashboard page heading + nav
  })

  it('renders a guarded staff route inside StaffLayout for an allowed role', () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/dashboard')
    expect(screen.getAllByText('Dashboard').length).toBeGreaterThan(0) // real Dashboard page + nav link
    expect(screen.getByText('Users')).toBeInTheDocument() // Sidebar nav item, proves StaffLayout mounted
  })

  it('renders a guarded customer route inside CustomerLayout', () => {
    renderAt(makeContextValue({ session: makeSession('customer'), status: 'authenticated' }), '/my-shipments')
    expect(screen.getAllByText('My Shipments').length).toBeGreaterThan(0) // real MyShipments page + nav link
    expect(screen.getByText('Account')).toBeInTheDocument() // CustomerTopNav link, proves CustomerLayout mounted
  })

  it('redirects an unauthenticated visitor hitting a protected route to /login', () => {
    renderAt(makeContextValue({}), '/dashboard')
    expect(screen.getByText('Sign in to ShipX')).toBeInTheDocument()
  })

  it("redirects a wrong-role visitor to their own role's home, not a blank screen", () => {
    renderAt(makeContextValue({ session: makeSession('customer'), status: 'authenticated' }), '/platform/dashboard')
    expect(screen.getAllByText('My Shipments').length).toBeGreaterThan(0) // landed on the customer's own home route
  })

  it('renders a 404 page for an unknown path instead of a blank screen', () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/this-route-does-not-exist')
    expect(screen.getByText('Page not found')).toBeInTheDocument()
  })

  it('tenant_admin sees Operations and Billing groups alongside admin-only nav, on the one shared Sidebar (no duplicated pages)', () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/containers')
    expect(screen.getAllByText('Containers').length).toBeGreaterThanOrEqual(1) // Operations group nav item
    expect(screen.getByText('Billing')).toBeInTheDocument() // Billing group nav item
    expect(screen.getByText('Users')).toBeInTheDocument() // Admin-only nav item
    expect(screen.getAllByText('Containers').length).toBeGreaterThanOrEqual(2) // page heading confirms real ContainerList rendered, not RouteStub
  })

  it('keeps the customer portal on the horizontal top-nav layout, never the staff sidebar', () => {
    renderAt(makeContextValue({ session: makeSession('customer'), status: 'authenticated' }), '/my-billing')
    // CustomerTopNav renders links as plain nav buttons; the staff Sidebar's
    // "Log out" footer button only exists in StaffLayout's AppSidebar.
    expect(screen.queryByText('Operations')).toBeNull()
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })
})
