import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { LocalRoleContext } from '../../auth/LocalRoleContext'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { LoginScreen } from './LoginScreen'

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

function renderLoginScreen(value: SessionContextValue, entry = '/login') {
  return render(
    <SessionContext.Provider value={value}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/login" element={<LoginScreen />} />
          <Route path="/dashboard" element={<div>Dashboard</div>} />
          <Route path="/platform/dashboard" element={<div>Platform dashboard</div>} />
          <Route path="/my-shipments" element={<div>My shipments</div>} />
          <Route path="/my-billing/:id" element={<div>The invoice</div>} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  )
}

function fakeSession(role: Session['role']): Session {
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
    expiresAt: Date.now() + 3_600_000,
    tokenType: 'cognito',
  }
}

describe('LoginScreen', () => {
  it('renders email and password fields plus the sign-in button', () => {
    renderLoginScreen(makeContextValue({}))
    expect(screen.getByLabelText('Email address', { exact: false, selector: 'input' })).toBeInTheDocument()
    expect(screen.getByLabelText('Password', { exact: false, selector: 'input' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('links back to the landing page and points shipping companies to Book a demo', () => {
    renderLoginScreen(makeContextValue({}))
    expect(screen.getByRole('link', { name: /back to home/i })).toHaveAttribute('href', '/')
    expect(screen.getAllByRole('link', { name: 'ShipX home' }).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByRole('link', { name: /book a demo/i })).toHaveAttribute('href', '/get-started')
  })

  it('redirects an already-authenticated user away from /login to their role home', () => {
    renderLoginScreen(
      makeContextValue({ status: 'authenticated', session: fakeSession('nigeria_office_staff') }),
    )
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
  })

  it('keeps /login reachable under LocalRoleContext so local dev & E2E can sign in with real credentials', () => {
    render(
      <LocalRoleContext.Provider value={{ identity: 'tenant_admin', setIdentity: vi.fn() }}>
        <SessionContext.Provider
          value={makeContextValue({ status: 'authenticated', session: fakeSession('tenant_admin') })}
        >
          <MemoryRouter initialEntries={['/login']}>
            <Routes>
              <Route path="/login" element={<LoginScreen />} />
              <Route path="/dashboard" element={<div>Dashboard</div>} />
            </Routes>
          </MemoryRouter>
        </SessionContext.Provider>
      </LocalRoleContext.Provider>,
    )
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByText('Dashboard')).toBeNull()
  })

  it('calls login with the entered credentials and redirects tenant staff to /dashboard', async () => {
    const login = vi.fn().mockResolvedValue(fakeSession('nigeria_office_staff'))
    renderLoginScreen(makeContextValue({ login }))

    await userEvent.type(screen.getByLabelText('Email address', { exact: false, selector: 'input' }), 'amara@acmelogistics.com')
    await userEvent.type(screen.getByLabelText('Password', { exact: false, selector: 'input' }), 'correct-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(login).toHaveBeenCalledWith('amara@acmelogistics.com', 'correct-password')
    expect(await screen.findByText('Dashboard')).toBeInTheDocument()
  })

  it('redirects platform_admin to /platform/dashboard', async () => {
    const login = vi.fn().mockResolvedValue(fakeSession('platform_admin'))
    renderLoginScreen(makeContextValue({ login }))
    await userEvent.type(screen.getByLabelText('Email address', { exact: false, selector: 'input' }), 'admin@shipx.co')
    await userEvent.type(screen.getByLabelText('Password', { exact: false, selector: 'input' }), 'pw')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Platform dashboard')).toBeInTheDocument()
  })

  it('redirects customer to /my-shipments', async () => {
    const login = vi.fn().mockResolvedValue(fakeSession('customer'))
    renderLoginScreen(makeContextValue({ login }))
    await userEvent.type(screen.getByLabelText('Email address', { exact: false, selector: 'input' }), 'ngozi@example.com')
    await userEvent.type(screen.getByLabelText('Password', { exact: false, selector: 'input' }), 'pw')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('My shipments')).toBeInTheDocument()
  })

  it('shows an error banner and stays on the page when login fails', async () => {
    const error = new Error('Incorrect username or password.')
    error.name = 'NotAuthorizedException'
    const login = vi.fn().mockRejectedValue(error)
    renderLoginScreen(makeContextValue({ login }))

    await userEvent.type(screen.getByLabelText('Email address', { exact: false, selector: 'input' }), 'amara@acmelogistics.com')
    await userEvent.type(screen.getByLabelText('Password', { exact: false, selector: 'input' }), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText("Couldn't sign in")).toBeInTheDocument()
    expect(screen.getByLabelText('Email address', { exact: false, selector: 'input' })).toBeInTheDocument()
  })

  it('toggles password visibility', async () => {
    renderLoginScreen(makeContextValue({}))
    const passwordInput = screen.getByLabelText('Password', { exact: false, selector: 'input' })
    expect(passwordInput).toHaveAttribute('type', 'password')

    await userEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(passwordInput).toHaveAttribute('type', 'text')

    await userEvent.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(passwordInput).toHaveAttribute('type', 'password')
  })

  it('disables the submit button while status is loading', () => {
    renderLoginScreen(makeContextValue({ status: 'loading' }))
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
  })
})

describe('LoginScreen return path (UX-04)', () => {
  async function signIn(entry: string, role: Session['role'] = 'customer') {
    const login = vi.fn().mockResolvedValue(fakeSession(role))
    renderLoginScreen(makeContextValue({ login }), entry)
    await userEvent.type(screen.getByLabelText(/email/i), 'a@example.test')
    await userEvent.type(screen.getByLabelText(/^password/i), 'pw')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
  }

  it('lands on the page the visitor was heading to', async () => {
    await signIn('/login?next=%2Fmy-billing%2Fabc')
    expect(await screen.findByText('The invoice')).toBeInTheDocument()
  })

  it('lands on the role home when there was no next', async () => {
    await signIn('/login')
    expect(await screen.findByText('My shipments')).toBeInTheDocument()
  })

  it.each(['https://example.com', '//example.com', '/%5C%5Cexample.com'])('ignores next=%s', async (next) => {
    await signIn(`/login?next=${encodeURIComponent(next)}`)
    expect(await screen.findByText('My shipments')).toBeInTheDocument()
  })
})
