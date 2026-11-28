import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { ImpersonationBanner } from './ImpersonationBanner'

function renderBanner(session: Session | null, exitImpersonation = vi.fn()) {
  const value: SessionContextValue = {
    status: session ? 'authenticated' : 'unauthenticated',
    session,
    login: vi.fn(),
    logout: vi.fn(),
    refreshNow: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation,
    setActiveRole: vi.fn(),
  }
  return {
    exitImpersonation,
    ...render(
      <SessionContext.Provider value={value}>
        <ImpersonationBanner />
      </SessionContext.Provider>,
    ),
  }
}

describe('ImpersonationBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-28T00:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not auto-exit on initial render when impersonation has remaining time', () => {
    const session: Session = {
      userId: 'admin-1',
      email: 'admin@acme.test',
      name: 'Tenant Admin',
      tenantId: 'tenant-1',
      tenantName: 'Acme Cargo',
      role: 'tenant_admin',
      roles: ['tenant_admin'],
      isPlatformAdmin: false,
      readOnly: true,
      impersonatedBy: 'platform@shipx.test',
      sessionId: 'sess-123',
      tokenType: 'impersonation',
      expiresAt: Date.now() + 30 * 60 * 1000,
    }
    const { exitImpersonation } = renderBanner(session)

    expect(exitImpersonation).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Acme Cargo')
    expect(screen.getByRole('alert')).toHaveTextContent('Ends in 30:00')
  })

  it('calls exitImpersonation when the user clicks Exit impersonation', () => {
    const session: Session = {
      userId: 'admin-1',
      email: 'admin@acme.test',
      name: 'Tenant Admin',
      tenantId: 'tenant-1',
      tenantName: 'Acme Cargo',
      role: 'tenant_admin',
      roles: ['tenant_admin'],
      isPlatformAdmin: false,
      readOnly: true,
      impersonatedBy: 'platform@shipx.test',
      sessionId: 'sess-123',
      tokenType: 'impersonation',
      expiresAt: Date.now() + 5 * 60 * 1000,
    }
    const { exitImpersonation } = renderBanner(session)

    fireEvent.click(screen.getByRole('button', { name: /exit impersonation/i }))
    expect(exitImpersonation).toHaveBeenCalledTimes(1)
  })

  it('auto-exits once the countdown actually reaches zero', () => {
    const session: Session = {
      userId: 'admin-1',
      email: 'admin@acme.test',
      name: 'Tenant Admin',
      tenantId: 'tenant-1',
      tenantName: 'Acme Cargo',
      role: 'tenant_admin',
      roles: ['tenant_admin'],
      isPlatformAdmin: false,
      readOnly: true,
      impersonatedBy: 'platform@shipx.test',
      sessionId: 'sess-123',
      tokenType: 'impersonation',
      expiresAt: Date.now() + 2000,
    }
    const { exitImpersonation } = renderBanner(session)

    expect(exitImpersonation).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(2500)
    })
    expect(exitImpersonation).toHaveBeenCalledTimes(1)
  })
})
