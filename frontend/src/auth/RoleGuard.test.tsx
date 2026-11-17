import { render, screen } from '@testing-library/react'
import type { JSX } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RoleGuard } from './RoleGuard'
import { SessionContext, type SessionContextValue } from './SessionContext'
import type { Session, UserRole } from './types'

function makeSession(role: UserRole, roles: UserRole[] = [role]): Session {
  return {
    tenantId: 't1',
    userId: 'u1',
    role,
    roles,
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  name: null,
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
    refreshNow: vi.fn(),
    setActiveRole: vi.fn(),
    ...overrides,
  }
}

function renderGuarded(value: SessionContextValue, allow: UserRole[]) {
  return render(
    <SessionContext.Provider value={value}>
      <MemoryRouter initialEntries={['/protected']}>
        <Routes>
          <Route
            path="/protected"
            element={
              <RoleGuard allow={allow}>
                <div>Protected content</div>
              </RoleGuard>
            }
          />
          <Route path="/login" element={<div>Login page</div>} />
          <Route path="/dashboard" element={<div>Tenant admin home</div>} />
          <Route path="/work-queue" element={<div>China staff home</div>} />
          <Route path="/my-shipments" element={<div>Customer home</div>} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  )
}

describe('RoleGuard', () => {
  it('renders children when the session role is allowed', () => {
    renderGuarded(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), [
      'tenant_admin',
    ])
    expect(screen.getByText('Protected content')).toBeInTheDocument()
  })

  it('redirects to /login when there is no session at all', () => {
    renderGuarded(makeContextValue({}), ['tenant_admin'])
    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  it('waits (does not redirect to /login) while a silent session restore is in flight', () => {
    renderGuarded(makeContextValue({ status: 'loading' }), ['tenant_admin'])
    expect(screen.queryByText('Login page')).toBeNull()
    expect(screen.queryByText('Protected content')).toBeNull()
  })

  it("redirects an authenticated-but-wrong-role visitor to that role's own home, not /login", () => {
    renderGuarded(makeContextValue({ session: makeSession('customer'), status: 'authenticated' }), [
      'tenant_admin',
    ])
    expect(screen.getByText('Customer home')).toBeInTheDocument()
    expect(screen.queryByText('Protected content')).toBeNull()
    expect(screen.queryByText('Login page')).toBeNull()
  })

  it("sends china_office_staff to /work-queue when blocked, not the tenant_admin home", () => {
    renderGuarded(makeContextValue({ session: makeSession('china_office_staff'), status: 'authenticated' }), [
      'tenant_admin',
    ])
    expect(screen.getByText('China staff home')).toBeInTheDocument()
  })

  it('allows a multi-role user in via a non-active role — authorization checks the full roles set', () => {
    // Active/display role is nigeria_office_staff, but warehouse_attendant
    // (a role they also hold) is what the route allows.
    const session = makeSession('nigeria_office_staff', ['nigeria_office_staff', 'warehouse_attendant'])
    renderGuarded(makeContextValue({ session, status: 'authenticated' }), ['warehouse_attendant'])
    expect(screen.getByText('Protected content')).toBeInTheDocument()
  })

  it('still blocks a multi-role user when none of their roles are allowed', () => {
    const session = makeSession('nigeria_office_staff', ['nigeria_office_staff', 'warehouse_attendant'])
    renderGuarded(makeContextValue({ session, status: 'authenticated' }), ['tenant_admin'])
    expect(screen.queryByText('Protected content')).toBeNull()
    // homePathForRole is keyed off the active role ('/dashboard' for nigeria_office_staff), not the full set.
    expect(screen.getByText('Tenant admin home')).toBeInTheDocument()
  })
})

describe('RoleGuard remembers where a signed-out visitor was going (UX-04)', () => {
  function Where(): JSX.Element {
    const l = useLocation()
    return <div data-testid="where">{`${l.pathname}${l.search}`}</div>
  }

  function renderDeepLink(entry: string) {
    return render(
      <SessionContext.Provider value={makeContextValue({})}>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/my-billing/:id" element={<RoleGuard allow={['customer']}><div>invoice</div></RoleGuard>} />
            <Route path="/login" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>,
    )
  }

  it('sends a signed-out visitor to /login with the page they asked for', () => {
    renderDeepLink('/my-billing/abc?tab=payments')
    expect(screen.getByTestId('where')).toHaveTextContent('/login?next=%2Fmy-billing%2Fabc%3Ftab%3Dpayments')
  })
})
