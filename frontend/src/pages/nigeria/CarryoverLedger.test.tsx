/**
 * The carryover ledger: debts rolled forward from releases with an outstanding balance (audit OPS-03: money-moving
 * pages are tested first).
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { carryoverApi, type Carryover } from '../../api/billing'
import { ApiError } from '../../api/client'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { withQuery } from '../../test/queryWrapper'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'
import { CarryoverLedger } from './CarryoverLedger'

vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return { ...original, carryoverApi: { list: vi.fn(), exempt: vi.fn() } }
})

function carryover(overrides: Partial<Carryover>): Carryover {
  return {
    id: 'co1',
    customer_id: 'cu1',
    customer_name: 'Ngozi Traders',
    source_billing_id: 'b-source-0001',
    source_container_number: 'ACME001',
    target_billing_id: null,
    amount_ngn: '45000.00',
    status: 'outstanding',
    created_at: '2026-11-10T09:00:00Z',
    ...overrides,
  }
}

const ROWS = [
  carryover({}),
  carryover({ id: 'co2', customer_name: 'Ade Imports', amount_ngn: '5000.50' }),
  carryover({ id: 'co3', customer_name: 'Chi Freight', amount_ngn: '90000.00', status: 'applied', target_billing_id: 'b9' }),
]

function ctx(role: Session['role']): SessionContextValue {
  return {
    session: {
      tenantId: 't1', userId: 'u1', name: null, role, roles: [role], isPlatformAdmin: false, impersonatedBy: null,
      sessionId: null, readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
    },
    status: 'authenticated',
    login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(),
    startImpersonation: vi.fn(), exitImpersonation: vi.fn(),
  }
}

function renderPage(role: Session['role'] = 'tenant_admin') {
  return render(
    withQuery(
      <MemoryRouter>
        <SessionContext.Provider value={ctx(role)}>
          <TopBarTestWrapper>
            <CarryoverLedger />
          </TopBarTestWrapper>
        </SessionContext.Provider>
      </MemoryRouter>,
    ),
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(carryoverApi.list).mockResolvedValue({ data: ROWS, meta: { pagination: { has_more: false, next_cursor: null, total_count: 3 } } } as Awaited<ReturnType<typeof carryoverApi.list>>)
})

describe('CarryoverLedger', () => {
  it('totals only what is still outstanding', async () => {
    renderPage()
    await screen.findByText('Ngozi Traders')
    // 45,000 + 5,000.50; the applied 90,000 is not owed. No row shows this figure, so it can only be the total.
    expect(screen.getByText('₦50,000.50')).toBeInTheDocument()
    expect(screen.queryByText('₦140,000.50')).toBeNull()
  })

  it('asks the server for the chosen status', async () => {
    renderPage()
    await screen.findByText('Ngozi Traders')
    await userEvent.click(screen.getByRole('button', { name: 'Applied' }))
    expect(carryoverApi.list).toHaveBeenLastCalledWith({ status: 'applied' })
  })

  it('lets only the tenant admin exempt, and only an outstanding entry', async () => {
    renderPage('tenant_admin')
    await screen.findByText('Ngozi Traders')
    expect(screen.getAllByRole('button', { name: 'Exempt' })).toHaveLength(2)
  })

  it('offers Nigeria staff no exemption', async () => {
    renderPage('nigeria_office_staff')
    await screen.findByText('Ngozi Traders')
    expect(screen.queryByRole('button', { name: 'Exempt' })).toBeNull()
  })

  it('exempts with the reason given and says the debt is rolled forward, not written off', async () => {
    vi.mocked(carryoverApi.exempt).mockResolvedValue(carryover({ status: 'exempted' }))
    renderPage()
    await screen.findByText('Ngozi Traders')
    await userEvent.click(screen.getAllByRole('button', { name: 'Exempt' })[0]!)
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/it is not written off/)).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'Agreed instalment plan')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Exempt carryover' }))
    expect(carryoverApi.exempt).toHaveBeenCalledWith('co1', 'Agreed instalment plan')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('keeps the dialog open and says why when the exemption is refused', async () => {
    vi.mocked(carryoverApi.exempt).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'x', status: 422, detail: "Carryover is already 'applied'", error_code: 'BUSINESS_RULE_VIOLATION' }, null),
    )
    renderPage()
    await screen.findByText('Ngozi Traders')
    await userEvent.click(screen.getAllByRole('button', { name: 'Exempt' })[0]!)
    await userEvent.click(screen.getByRole('button', { name: 'Exempt carryover' }))
    expect(await screen.findByText("Carryover is already 'applied'")).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
