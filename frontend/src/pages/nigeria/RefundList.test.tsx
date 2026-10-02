import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import * as refundsModule from '../../api/refunds'
import { SessionContext } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { RefundList } from './RefundList'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'

const SESSION: Session = {
  userId: 'u-001',
  tenantId: 't-001',
  role: 'nigeria_office_staff',
  roles: ['nigeria_office_staff'],
  name: 'Staff',
  email: 'staff@test.com',
  isPlatformAdmin: false,
  impersonatedBy: null,
  sessionId: null,
  readOnly: false,
  expiresAt: Date.now() + 60_000,
  tokenType: 'cognito',
}

function renderPage() {
  vi.spyOn(refundsModule.refundsApi, 'list').mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
  return render(
    <QueryClientProvider client={__qc()}><MemoryRouter>
      <SessionContext.Provider value={{ session: SESSION, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }}>
        <TopBarTestWrapper><RefundList /></TopBarTestWrapper>
      </SessionContext.Provider>
    </MemoryRouter></QueryClientProvider>,
  )
}

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('RefundList', () => {
  it('renders page header', async () => {
    renderPage()
    expect(screen.getByText(/Track refund requests/)).toBeTruthy()
  })

  it('shows empty state when no refunds', async () => {
    renderPage()
    expect(await screen.findByText(/No refund requests match/)).toBeTruthy()
  })
})
