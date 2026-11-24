/**
 * Action component — read-only impersonation enforcement test (Task 08 / Task 12).
 *
 * The Action component is the single chokepoint for read-only impersonation in
 * the UI, mirroring get_tenant_context() on the backend. This test verifies:
 * - Normal session: renders as a live Button (clickable)
 * - Read-only session: a disabled button with the reason as its title (FD-07: Button does this itself)
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { Action } from './Action'
import { Button } from './Button'
import { IconButton } from './IconButton'

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

  it('is a disabled button during read-only impersonation, and says why', () => {
    renderWithSession(
      <Action variant="primary" onClick={vi.fn()}>Approve</Action>,
      baseSession({ readOnly: true, impersonatedBy: 'platform@shipx.co', tokenType: 'impersonation' }),
    )
    const button = screen.getByRole('button', { name: /approve/i })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', 'Disabled during read-only impersonation')
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

  it('blocks a mutating Button without an Action wrapper (FD-07)', () => {
    renderWithSession(
      <>
        <Button variant="primary">Save</Button>
        <Button variant="danger-ghost">Cancel container</Button>
        <Button variant="secondary">Filter</Button>
        <Button variant="secondary" mutates>Archive</Button>
        <Button variant="primary" mutates={false}>Open</Button>
        <IconButton icon="x" label="Remove item" variant="danger-ghost" />
      </>,
      baseSession({ readOnly: true, impersonatedBy: 'platform@shipx.co' }),
    )
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /cancel container/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /archive/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /remove item/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /filter/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /open/i })).toBeEnabled()
  })

  it('leaves every button live outside impersonation and with no session at all', () => {
    render(<Button variant="primary">Sign in</Button>)
    expect(screen.getByRole('button', { name: /sign in/i })).toBeEnabled()
  })
})
