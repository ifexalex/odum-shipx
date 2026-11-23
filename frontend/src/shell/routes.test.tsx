import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { AppRoutes } from './routes'
import { routeTable } from './routeTable'
import { GUARDED_SCREENS, PUBLIC_SCREENS, screenForRoute } from './screens'

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

  it("redirects / to the visitor's own home when signed in", async () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/')
    expect((await screen.findAllByText('Dashboard')).length).toBeGreaterThan(0) // real Dashboard page heading + nav
  })

  it('renders a guarded staff route inside StaffLayout for an allowed role', async () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/dashboard')
    expect((await screen.findAllByText('Dashboard')).length).toBeGreaterThan(0) // real Dashboard page + nav link
    expect(await screen.findByText('Users')).toBeInTheDocument() // Sidebar nav item, proves StaffLayout mounted
  })

  it('renders a guarded customer route inside CustomerLayout', async () => {
    renderAt(makeContextValue({ session: makeSession('customer'), status: 'authenticated' }), '/my-shipments')
    expect((await screen.findAllByText('My Shipments')).length).toBeGreaterThan(0) // real MyShipments page + nav link
    expect(await screen.findByText('Account')).toBeInTheDocument() // CustomerTopNav link, proves CustomerLayout mounted
  })

  it('redirects an unauthenticated visitor hitting a protected route to /login', () => {
    renderAt(makeContextValue({}), '/dashboard')
    expect(screen.getByText('Sign in to ShipX')).toBeInTheDocument()
  })

  it("redirects a wrong-role visitor to their own role's home, not a blank screen", async () => {
    renderAt(makeContextValue({ session: makeSession('customer'), status: 'authenticated' }), '/platform/dashboard')
    expect((await screen.findAllByText('My Shipments')).length).toBeGreaterThan(0) // landed on the customer's own home route
  })

  it('renders a 404 page for an unknown path instead of a blank screen', () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/this-route-does-not-exist')
    expect(screen.getByText('Page not found')).toBeInTheDocument()
  })

  it('tenant_admin sees Operations and Billing groups alongside admin-only nav, on the one shared Sidebar (no duplicated pages)', async () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/containers')
    expect(await screen.findByText('Billing')).toBeInTheDocument() // Billing group nav item
    expect(screen.getAllByText('Containers').length).toBeGreaterThanOrEqual(1) // Operations group nav item
    expect(screen.getByText('Users')).toBeInTheDocument() // Admin-only nav item
    // The page itself (its own heading) proves the real ContainerList rendered, not RouteStub.
    await waitFor(() => expect(screen.getAllByText('Containers').length).toBeGreaterThanOrEqual(2))
  })

  it('keeps the customer portal on the horizontal top-nav layout, never the staff sidebar', async () => {
    renderAt(makeContextValue({ session: makeSession('customer'), status: 'authenticated' }), '/my-billing')
    // CustomerTopNav renders links as plain nav buttons; the staff Sidebar's
    // "Log out" footer button only exists in StaffLayout's AppSidebar.
    expect(await screen.findByRole('button', { name: 'Log out' })).toBeInTheDocument()
    expect(screen.queryByText('Operations')).toBeNull()
  })

  it('shows the loading spinner, not a blank screen, while a page chunk downloads', async () => {
    const { container } = renderAt(
      makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }),
      '/admin/reports',
    )
    // Nothing has loaded yet on the first render: the fallback is what is on screen.
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull()
    // A cold page chunk can take over a second to compile when the whole suite runs in parallel.
    expect((await screen.findAllByText('Users', {}, { timeout: 5000 })).length).toBeGreaterThan(0)
    await waitFor(() => expect(container.querySelector('[aria-busy="true"]')).toBeNull())
  })
})

// Drift guard for FE-02. Code splitting survives only while nothing in the route table imports a page statically:
// one such import drags that page, and everything it imports, back into the entry chunk for every visitor.
// The route tree (routes.tsx) and the screen maps it renders (screens.tsx), read together: an eager import in either
// lands in the entry chunk.
const ROUTES_SOURCE = Object.values(
  import.meta.glob(['./routes.tsx', './screens.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<
    string,
    string
  >,
).join('\n')

describe('code splitting (FE-02)', () => {
  // The screens a visitor needs before they are signed in. Everything else loads on demand.
  const ENTRY_PAGES = ['pages/auth/AuthCallback', 'pages/auth/LoginScreen', 'pages/marketing/LandingPage', 'pages/customer/PublicTrack']

  it('imports only the sign-in, landing, tracking and callback pages statically', () => {
    const staticPageImports = [...ROUTES_SOURCE.matchAll(/^import .* from '\.\.\/(pages\/[^']+)'/gm)].map((m) => m[1])
    expect(staticPageImports.sort()).toEqual([...ENTRY_PAGES].sort())
  })

  it('does not import a layout statically either', () => {
    expect(ROUTES_SOURCE).not.toMatch(/^import .* from '\.\/(Staff|Customer)Layout'/m)
  })

  it('loads every other page through the area modules', () => {
    expect(ROUTES_SOURCE).toMatch(/import\('\.\/areas\/china'\)/)
    expect(ROUTES_SOURCE).toMatch(/import\('\.\/areas\/customer'\)/)
  })
})

describe('every route has a real screen (FE-08)', () => {
  // A route added to routeTable.ts without a screen used to render a "lands in Task 07" placeholder, silently.
  it.each(routeTable.map((route) => [route.path, route] as const))('%s', (_path, route) => {
    expect(screenForRoute(route), `no screen registered for ${route.path}`).toBeDefined()
  })

  it('registers no screen for a route that does not exist, or under the wrong guard', () => {
    const publicPaths = new Set(routeTable.filter((r) => r.allow === 'public').map((r) => r.path))
    const guardedPaths = new Set(routeTable.filter((r) => r.allow !== 'public').map((r) => r.path))
    // A guarded page in PUBLIC_SCREENS would render without a RoleGuard.
    expect(Object.keys(PUBLIC_SCREENS).filter((path) => !publicPaths.has(path))).toEqual([])
    expect(Object.keys(GUARDED_SCREENS).filter((path) => !guardedPaths.has(path))).toEqual([])
  })

  it('declares each path once', () => {
    const paths = routeTable.map((r) => r.path)
    expect(paths.filter((path, i) => paths.indexOf(path) !== i)).toEqual([])
  })
})

