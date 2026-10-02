/**
 * Read-only impersonation sweep (Task 08 acceptance criterion).
 *
 * Renders a sample of the highest-traffic detail pages under a read-only
 * impersonation session and asserts that every mutating *opener* control is
 * rendered non-interactive (the Action component's disabled dashed span,
 * `aria-disabled="true"` with `role="button"`, never a live <button>).
 *
 * These pages accept their entity via router state, so no API/network is
 * needed — the read-only enforcement is what's under test, not data loading.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { BillingDetail } from './nigeria/BillingDetail'
import { ClaimDetail } from './nigeria/ClaimDetail'
import { RefundDetail } from './nigeria/RefundDetail'
import { ReleaseNoteDetail } from './nigeria/ReleaseNoteDetail'

// A read-only session mimics a platform admin impersonating a tenant.
function readOnlySession(): Session {
  return {
    tenantId: 't1',
    tenantName: 'Acme Logistics',
    userId: 'platform-1',
    name: 'Platform Admin',
    role: 'tenant_admin',
    roles: ['tenant_admin'],
    isPlatformAdmin: true,
    impersonatedBy: 'platform-1',
    sessionId: 'imp-1',
    readOnly: true,
    expiresAt: Date.now() + 60_000,
    tokenType: 'impersonation',
  }
}

function renderReadOnly(path: string, routePattern: string, element: ReactNode, state: unknown) {
  const ctx: SessionContextValue = {
    session: readOnlySession(),
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider value={ctx}>
        <MemoryRouter initialEntries={[{ pathname: path, state }]}>
          <Routes>
            <Route path={routePattern} element={element} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

// The labels of the mutating openers on each page — none may render as a live
// <button> under a read-only session (Action turns them into aria-disabled spans).
const MUTATING_LABELS = [
  /record payment/i, /add charge/i, /apply carryover/i, /generate release note/i, /cancel billing/i,
  /start inspection/i, /resolve/i,
  /accounts review/i, /approve/i, /reject/i,
  /record pickup/i, /split note/i, /re-issue/i,
]

function assertNoLiveMutators(): void {
  const buttons = screen.queryAllByRole('button')
  for (const btn of buttons) {
    // Action's read-only render is a <span role="button" aria-disabled="true">.
    if (btn.tagName.toLowerCase() === 'span') continue
    const label = btn.textContent ?? ''
    for (const re of MUTATING_LABELS) {
      expect(re.test(label), `Live mutating control "${label}" rendered under read-only`).toBe(false)
    }
  }
}

const BILLING = {
  id: 'b1', invoice_number: 'INV-1', customer_id: 'c1', customer_name: 'Ngozi',
  container_id: 'cont1', container_number: 'ACME-001', total_cbm: '2.5', cbm_rate_usd: '45',
  dollar_rate: '1550', subtotal_usd: '112', subtotal_ngn: '174000', misc_fees: [], misc_fees_ngn: 0,
  adjustments_ngn: '0', carryover_ngn: 0, storage_fees_ngn: 0, total_due_ngn: '174000',
  total_paid_ngn: '0', outstanding_ngn: '174000', payment_status: 'unpaid' as const,
  released_with_outstanding: false, billed_at: null, payments: [], carryovers: [], _active_disputes: [],
}

const CLAIM = {
  id: 'dc1', reference: 'DC-1', status: 'filed' as const, container_id: null, container_number: 'ACME-001',
  customer_id: null, customer_name: 'Ngozi', description: 'Water damage', inspection_method: null,
  cartons_affected: ['C1'], upload_urls: null, created_at: '2026-06-01T10:00:00Z',
}

const REFUND = {
  id: 'r1', status: 'pending_approval' as const, refund_type: 'overpayment' as const,
  amount_requested_ngn: '25000', amount_approved_ngn: null, customer_choice: 'immediate_refund' as const,
  customer_id: 'c1', billing_id: 'b1', damage_claim_id: null, reason: 'Overpaid', rejection_reason: null,
  approval_level: 'manager' as const, debt_check_passed: null, debt_check_notes: null,
  created_at: '2026-07-01T00:00:00Z', threshold: null,
}

const NOTE = {
  id: 'rn1', reference_number: 'RN-1', customer_name: 'Ngozi', container_number: 'ACME-001',
  carton_count: 5, total_cartons_for_customer: 5, is_partial_release: false, carton_tags: ['C1'],
  payment_status: 'paid', status: 'active' as const, authorized_at: '2026-07-01T00:00:00Z',
  warehouse_address: null, packages_released: null, package_unit: null, packages_balance: null,
  warehouse_name: null, warehouse_phone: null, is_on_credit: false,
  credit_granted_by_name: null, receipt_number: null,
  physical_document_number: null, packing_list_invoice_numbers: [],
  amount_paid_ngn: '0', balance_ngn: '0', total_ngn: '0', debt_due_date: null,
}

describe('read-only impersonation — no live mutating controls', () => {
  it('BillingDetail', () => {
    renderReadOnly('/billing/b1', '/billing/:id', <BillingDetail />, { billing: BILLING })
    assertNoLiveMutators()
  })

  it('ClaimDetail', () => {
    renderReadOnly('/claims/dc1', '/claims/:id', <ClaimDetail />, { claim: CLAIM })
    assertNoLiveMutators()
  })

  it('RefundDetail', () => {
    renderReadOnly('/refunds/r1', '/refunds/:id', <RefundDetail />, { refund: REFUND })
    assertNoLiveMutators()
  })

  it('ReleaseNoteDetail', () => {
    renderReadOnly('/release-notes/rn1', '/release-notes/:id', <ReleaseNoteDetail />, { note: NOTE })
    assertNoLiveMutators()
  })
})
