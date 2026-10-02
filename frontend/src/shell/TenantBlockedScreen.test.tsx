/**
 * 16.12 / audit gap A4 — tenant offboarded (410) / suspended (403) full-page
 * gate: the API client trips auth/tenantGate on the error codes, and the
 * layouts swap ALL routed content for TenantBlockedScreen.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearTenantBlocked, getTenantBlocked, reportTenantBlocked } from '../auth/tenantGate'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { TenantBlockedGate } from './TenantBlockedScreen'

function makeCtx(logout = vi.fn()): SessionContextValue {
  const session: Session = {
    tenantId: 't1',
    userId: 'u1',
    name: 'Amara',
    role: 'tenant_admin',
    roles: ['tenant_admin'],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
  return {
    session,
    status: 'authenticated',
    login: vi.fn(),
    logout,
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
}

function renderGate(logout = vi.fn()) {
  return render(
    <SessionContext.Provider value={makeCtx(logout)}>
      <TenantBlockedGate>
        <div>Routed page content</div>
      </TenantBlockedGate>
    </SessionContext.Provider>,
  )
}

describe('tenantGate store', () => {
  afterEach(() => clearTenantBlocked())

  it('trips on TENANT_OFFBOARDED and TENANT_SUSPENDED, ignores other codes', () => {
    reportTenantBlocked('RESOURCE_NOT_FOUND')
    expect(getTenantBlocked()).toBeNull()

    reportTenantBlocked('TENANT_SUSPENDED')
    expect(getTenantBlocked()).toBe('suspended')

    reportTenantBlocked('TENANT_OFFBOARDED')
    expect(getTenantBlocked()).toBe('offboarded')

    clearTenantBlocked()
    expect(getTenantBlocked()).toBeNull()
  })
})

describe('TenantBlockedGate', () => {
  beforeEach(() => clearTenantBlocked())
  afterEach(() => clearTenantBlocked())

  it('renders children while the tenant is healthy', () => {
    renderGate()
    expect(screen.getByText('Routed page content')).toBeInTheDocument()
  })

  it('swaps content for the closed-account page when the tenant is offboarded', () => {
    renderGate()
    act(() => reportTenantBlocked('TENANT_OFFBOARDED'))

    expect(screen.getByText('This account has been closed')).toBeInTheDocument()
    expect(screen.getByText('HTTP 410 · TENANT_OFFBOARDED')).toBeInTheDocument()
    expect(screen.queryByText('Routed page content')).toBeNull()
    // Contact support mailto CTA
    expect(screen.getByText('Contact support').closest('a')).toHaveAttribute('href', 'mailto:support@shipx.co')
  })

  it('shows the suspended variant with its own copy and code', () => {
    renderGate()
    act(() => reportTenantBlocked('TENANT_SUSPENDED'))

    expect(screen.getByText('This account is suspended')).toBeInTheDocument()
    expect(screen.getByText('HTTP 403 · TENANT_SUSPENDED')).toBeInTheDocument()
  })

  it('offers sign-out so a user with another account can leave', async () => {
    const logout = vi.fn()
    renderGate(logout)
    act(() => reportTenantBlocked('TENANT_OFFBOARDED'))

    await userEvent.click(screen.getByRole('button', { name: /sign out/i }))
    expect(logout).toHaveBeenCalledOnce()
  })
})
