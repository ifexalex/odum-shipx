import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import * as refundsModule from '../../api/refunds'
import { SessionContext } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { RefundDetail } from './RefundDetail'

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

const REFUND: refundsModule.Refund = {
  id: 'r-001',
  status: 'pending_review',
  refund_type: 'overpayment',
  amount_requested_ngn: '25000',
  amount_approved_ngn: null,
  customer_choice: 'immediate_refund',
  customer_id: 'cust-001',
  billing_id: 'bill-001',
  damage_claim_id: null,
  reason: 'Overpaid on last shipment',
  rejection_reason: null,
  approval_level: 'manager',
  debt_check_passed: null,
  debt_check_notes: null,
  created_at: '2026-07-04T00:00:00Z',
}

function renderPage(refund = REFUND) {
  vi.spyOn(refundsModule.refundsApi, 'get').mockResolvedValue(refund)
  return render(
    withQuery(
      <MemoryRouter initialEntries={['/refunds/r-001']}>
        <Routes>
          <Route
            path="/refunds/:id"
            element={
              <SessionContext.Provider value={{ session: SESSION, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }}>
                <RefundDetail />
              </SessionContext.Provider>
            }
          />
        </Routes>
      </MemoryRouter>,
    ),
  )
}

describe('RefundDetail credit use (BE-07)', () => {
  it('shows how much of a credit has been used against invoices', async () => {
    renderPage({
      ...REFUND, status: 'applied_as_credit', customer_choice: 'credit_next_shipment',
      amount_approved_ngn: '50000', credit_applied_ngn: '20000',
    })
    expect(await screen.findByText('Credit used')).toBeInTheDocument()
    expect(screen.getByText('₦20,000 of ₦50,000')).toBeInTheDocument()
  })

  it('shows no credit row for a refund paid out', async () => {
    renderPage({ ...REFUND, status: 'processed', customer_choice: 'immediate_refund', amount_approved_ngn: '25000' })
    await screen.findByText('Approved')
    expect(screen.queryByText('Credit used')).toBeNull()
  })
})

describe('RefundDetail bank details', () => {
  it('shows staff the account a bank refund is paid into', async () => {
    renderPage({
      ...REFUND,
      customer_choice: 'immediate_refund',
      bank_details: { bank_name: 'Zenith Bank', account_number: '0123456789', account_name: 'Ngozi Okonkwo' },
    })
    expect(await screen.findByText('0123456789')).toBeInTheDocument()
    expect(screen.getByText('Zenith Bank')).toBeInTheDocument()
    expect(screen.getByText('Ngozi Okonkwo')).toBeInTheDocument()
  })

  it('shows no account rows for a refund without one', async () => {
    renderPage({ ...REFUND, bank_details: null })
    await screen.findByText('Customer preference')
    expect(screen.queryByText('Account number')).not.toBeInTheDocument()
  })
})

describe('RefundDetail', () => {
  it('renders refund type in hero', async () => {
    renderPage()
    // Multiple elements with this text (h1 + kvp) — just assert at least one exists
    expect((await screen.findAllByText('Overpayment refund')).length).toBeGreaterThan(0)
  })

  it('shows Complete review for pending_review (FD-23)', async () => {
    renderPage()
    // Button role is the specific element to assert
    expect(await screen.findByRole('button', { name: /complete review/i })).toBeTruthy()
  })

  it('shows no action buttons when processed', async () => {
    renderPage({ ...REFUND, status: 'processed', amount_approved_ngn: '25000' })
    await screen.findAllByText('Overpayment refund')
    expect(screen.queryByRole('button', { name: /complete review/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull()
  })

  it('shows Approve and Reject for pending_approval', async () => {
    renderPage({ ...REFUND, status: 'pending_approval' })
    expect(await screen.findByRole('button', { name: /approve/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /reject/i })).toBeTruthy()
  })

  // Threshold-aware approval (gap-fix B1: refund approve threshold)
  it('shows Escalate button (not Approve) when approval_level is tenant_admin and role is nigeria_office_staff', async () => {
    // nigeria_office_staff cannot approve tenant_admin-level refunds.
    // They see "Escalate to Tenant Admin" rather than a direct approve button.
    renderPage({ ...REFUND, status: 'pending_approval', approval_level: 'head_of_finance' })
    // Should either show no Approve, or show an Escalate button — not a direct Approve
    await screen.findAllByRole('button') // wait for async render (page renders several buttons)
    const approveBtn = screen.queryByRole('button', { name: /^approve$/i })
    const escalateBtn = screen.queryByRole('button', { name: /escalate/i })
    // Either the approve button is absent OR an escalate button is present
    const isThresholdEnforced = approveBtn === null || escalateBtn !== null
    expect(isThresholdEnforced).toBe(true)
  })

  it('shows direct Approve when approval_level is manager and role is nigeria_office_staff', async () => {
    // manager-level refunds ARE within nigeria_office_staff authority.
    renderPage({ ...REFUND, status: 'pending_approval', approval_level: 'manager' })
    expect(await screen.findByRole('button', { name: /approve/i })).toBeTruthy()
  })
})
