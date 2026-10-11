import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { AppSidebar } from './AppSidebar'

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
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>
          <AppSidebar />
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

describe('AppSidebar', () => {
  it('renders nothing when there is no session', () => {
    const { container } = renderAt(makeContextValue({}), '/dashboard')
    expect(container).toBeEmptyDOMElement()
  })

  it("renders the tenant admin's nav and marks the current path active", () => {
    renderAt(makeContextValue({ session: makeSession('tenant_admin'), status: 'authenticated' }), '/admin/users')
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Users')).toBeInTheDocument()
    expect(screen.getByText('Operations')).toBeInTheDocument()
  })

  it('shows the platform admin onboarding-requests nav entry', () => {
    renderAt(makeContextValue({ session: makeSession('platform_admin'), status: 'authenticated' }), '/platform/dashboard')
    expect(screen.getByText('Onboarding Requests')).toBeInTheDocument()
    expect(screen.getByText('Tenants')).toBeInTheDocument()
  })

  it('calls logout when the logout button is clicked', async () => {
    const logout = vi.fn()
    renderAt(makeContextValue({ session: makeSession('china_office_staff'), status: 'authenticated', logout }), '/containers')
    await userEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(logout).toHaveBeenCalledOnce()
  })

  it('shows china_office_staff Operations/Packing lists/Coordination nav groups, not admin nav', () => {
    renderAt(makeContextValue({ session: makeSession('china_office_staff'), status: 'authenticated' }), '/containers')
    expect(screen.getByText('Operations')).toBeInTheDocument()   // group label
    expect(screen.getByText('All packing lists')).toBeInTheDocument() // updated nav label
    expect(screen.getByText('Coordination')).toBeInTheDocument() // group label
    expect(screen.queryByText('Users')).toBeNull()
  })
})
