/**
 * Platform admin sign-in (platform audit Phase 1b): its own Cognito pool, then the authenticator code or its setup.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MfaCodeRequiredError, MfaSetupRequiredError } from '../../auth/CognitoClient'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { LoginScreen } from './LoginScreen'

const platformSession = {
  tenantId: 'PLATFORM',
  userId: 'u1',
  role: 'platform_admin',
  roles: ['platform_admin'],
  isPlatformAdmin: true,
} as unknown as Session

function value(overrides: Partial<SessionContextValue>): SessionContextValue {
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
  } as SessionContextValue
}

function renderAt(entry: string, ctx: SessionContextValue) {
  return render(
    <SessionContext.Provider value={ctx}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/login" element={<LoginScreen />} />
          <Route path="/platform/dashboard" element={<div>Platform dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  )
}

async function signInWithPassword(): Promise<void> {
  await userEvent.type(screen.getByLabelText('Email address', { exact: false, selector: 'input' }), 'admin@shipx.test')
  await userEvent.type(screen.getByLabelText('Password', { exact: false, selector: 'input' }), 'correct horse')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

beforeEach(() => {
  vi.stubEnv('VITE_COGNITO_PLATFORM_USER_POOL_ID', 'platform-pool')
  vi.stubEnv('VITE_COGNITO_PLATFORM_CLIENT_ID', 'platform-client')
})

describe('Platform admin sign-in', () => {
  it('is offered from the standard sign-in', () => {
    renderAt('/login', value({}))
    expect(screen.getByRole('link', { name: /platform admin\? sign in here/i })).toHaveAttribute('href', '/login?platform=1')
  })

  it('signs in to the platform pool, then takes the authenticator code', async () => {
    const login = vi.fn().mockRejectedValue(new MfaCodeRequiredError())
    const completeMfa = vi.fn().mockResolvedValue(platformSession)
    renderAt('/login?platform=1', value({ login, completeMfa }))
    expect(screen.getByText('Platform admin sign-in')).toBeInTheDocument()

    await signInWithPassword()
    expect(login).toHaveBeenCalledWith('admin@shipx.test', 'correct horse', { pool: 'platform' })

    await userEvent.type(await screen.findByLabelText(/Authenticator code/), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(completeMfa).toHaveBeenCalledWith('code', '123456')
    expect(await screen.findByText('Platform dashboard')).toBeInTheDocument()
  })

  it('shows the setup key on a first sign-in', async () => {
    const login = vi.fn().mockRejectedValue(new MfaSetupRequiredError('SECRETKEY', 'admin@shipx.test'))
    const completeMfa = vi.fn().mockResolvedValue(platformSession)
    renderAt('/login?platform=1', value({ login, completeMfa }))
    await signInWithPassword()
    expect(await screen.findByText('Set up your authenticator')).toBeInTheDocument()
    expect(screen.getByText('SECRETKEY')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Authenticator code/), '654321')
    await userEvent.click(screen.getByRole('button', { name: 'Finish setup' }))
    expect(completeMfa).toHaveBeenCalledWith('setup', '654321')
  })

  it('explains a wrong code', async () => {
    const login = vi.fn().mockRejectedValue(new MfaCodeRequiredError())
    const mismatch = Object.assign(new Error('Invalid code'), { name: 'CodeMismatchException' })
    const completeMfa = vi.fn().mockRejectedValue(mismatch)
    renderAt('/login?platform=1', value({ login, completeMfa }))
    await signInWithPassword()
    await userEvent.type(await screen.findByLabelText(/Authenticator code/), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByText(/That code is not right/)).toBeInTheDocument()
  })

  it('stays the standard sign-in when the build has no platform pool', () => {
    vi.stubEnv('VITE_COGNITO_PLATFORM_USER_POOL_ID', '')
    renderAt('/login?platform=1', value({}))
    expect(screen.getByText('Sign in to ShipX')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /platform admin/i })).toBeNull()
  })
})
