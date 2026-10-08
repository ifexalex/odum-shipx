/**
 * Action component — read-only impersonation enforcement test (Task 08 / Task 12).
 *
 * The Action component is the single chokepoint for read-only impersonation in
 * the UI, mirroring get_tenant_context() on the backend. This test verifies:
 * - Normal session: renders as a live Button (clickable)
 * - Read-only session: renders as a dashed disabled pill (not clickable)
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { Action } from './Action'

function baseSession(overrides: Partial<Session> = {}): Session {
  return {
    tenantId: 'tenant-1',
    tenantName: null,
    userId: 'user-1',
    name: 'Test User',
    role: 'tenant_admin',
    roles: ['tenant_admin'],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
    ...overrides,
  }
}

function renderWithSession(ui: React.ReactNode, session: Session) {
  const ctx: SessionContextValue = {
    session,
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(),
    setActiveRole: vi.fn(),
  }
  return render(
    <SessionContext.Provider value={ctx}>{ui}</SessionContext.Provider>,
  )
}

describe('Action — read-only impersonation enforcement', () => {
  it('renders as a live button in a normal (non-read-only) session', async () => {
    const onClick = vi.fn()
    renderWithSession(
      <Action variant="primary" onClick={onClick}>Approve</Action>,
      baseSession({ readOnly: false }),
    )

    const btn = screen.getByRole('button', { name: /approve/i })
    expect(btn).toBeEnabled()
    await userEvent.click(btn)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('renders as a disabled dashed pill during read-only impersonation', () => {
    const onClick = vi.fn()
    renderWithSession(
      <Action variant="primary" onClick={onClick}>Approve</Action>,
      baseSession({
        readOnly: true,
        impersonatedBy: 'platform@shipx.co',
        tokenType: 'impersonation',
      }),
    )

    // The read-only pill has role="button" and aria-disabled="true".
    // It must NOT render as a native <button> (which has a real click handler).
    const pill = screen.getByRole('button', { name: /approve/i })

    // aria-disabled marks it as non-interactive for assistive technology
    expect(pill).toHaveAttribute('aria-disabled', 'true')

    // It should be a <span>, not a native <button> — native buttons stay clickable
    // even with aria-disabled unless explicitly disabled via the disabled attr.
    expect(pill.tagName.toLowerCase()).toBe('span')
  })

  it('never fires onClick during read-only impersonation', async () => {
    const onClick = vi.fn()
    renderWithSession(
      <Action variant="danger" onClick={onClick}>Delete</Action>,
      baseSession({ readOnly: true, impersonatedBy: 'platform@shipx.co' }),
    )

    // Clicking anything visible must not invoke the handler
    const elements = screen.getAllByText('Delete')
    for (const el of elements) {
      await userEvent.click(el, { pointerEventsCheck: 0 })
    }
    expect(onClick).not.toHaveBeenCalled()
  })

  it('shows the disabled tooltip on the pill', () => {
    renderWithSession(
      <Action variant="primary">Save</Action>,
      baseSession({ readOnly: true }),
    )

    const pill = screen.getByText('Save').closest('[aria-disabled]')
    expect(pill).toHaveAttribute('title', 'Disabled during read-only impersonation')
  })
})
