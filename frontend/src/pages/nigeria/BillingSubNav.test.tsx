import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { BillingSubNav, type BillingSubNavTab } from './BillingSubNav'

function renderNav(role: Session['role'], active: BillingSubNavTab = 'invoices') {
  const session: Session = {
    tenantId: 't1',
    userId: 'u1',
    name: 'Test User',
    role,
    roles: [role],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
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
    <SessionContext.Provider value={ctx}>
      <MemoryRouter initialEntries={['/billing']}>
        <Routes>
          <Route path="/billing" element={<BillingSubNav active={active} />} />
          <Route path="/billing/disputes" element={<div>Disputes page</div>} />
          <Route path="/billing/carryovers" element={<div>Carryovers page</div>} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  )
}

describe('BillingSubNav', () => {
  it('renders Invoices, CBM disputes, and Carryovers tabs for Nigeria staff and navigates on click', async () => {
    renderNav('nigeria_office_staff', 'invoices')
    expect(screen.getByRole('tab', { name: 'Invoices' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'CBM disputes' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Carryovers' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'CBM disputes' }))
    expect(await screen.findByText('Disputes page')).toBeInTheDocument()
  })

  it('renders for tenant_admin and navigates to Carryovers', async () => {
    renderNav('tenant_admin', 'invoices')
    await userEvent.click(screen.getByRole('tab', { name: 'Carryovers' }))
    expect(await screen.findByText('Carryovers page')).toBeInTheDocument()
  })

  it('hides billing sub-nav for china_office_staff who may not read invoices', () => {
    const { container } = renderNav('china_office_staff', 'disputes')
    expect(container).toBeEmptyDOMElement()
  })
})
