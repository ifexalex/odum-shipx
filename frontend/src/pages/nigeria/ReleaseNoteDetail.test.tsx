import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import * as rnModule from '../../api/releaseNotes'
import { warehousesApi } from '../../api/warehouses'
import { usersApi } from '../../api/tenantManagement'
import { SessionContext } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { ReleaseNoteDetail } from './ReleaseNoteDetail'

const WAREHOUSE_SESSION: Session = {
  userId: 'u-wh', tenantId: 't-001', role: 'warehouse_attendant', roles: ['warehouse_attendant'],
  name: 'Tunde', email: 'wh@test.com',
  isPlatformAdmin: false,
  impersonatedBy: null,
  sessionId: null,
  readOnly: false,
  expiresAt: Date.now() + 60_000,
  tokenType: 'cognito',
}
const STAFF_SESSION: Session = {
  userId: 'u-ng', tenantId: 't-001', role: 'nigeria_office_staff', roles: ['nigeria_office_staff'],
  name: 'Emeka', email: 'ng@test.com',
  isPlatformAdmin: false,
  impersonatedBy: null,
  sessionId: null,
  readOnly: false,
  expiresAt: Date.now() + 60_000,
  tokenType: 'cognito',
}

const NOTE: rnModule.ReleaseNote = {
  id: 'rn-001', reference_number: 'ACME-RN-20260704-0001',
  customer_name: 'Chioma Eze', container_number: 'ACME001001',
  carton_count: 3, total_cartons_for_customer: 5,
  is_partial_release: true, carton_tags: ['A', 'B', 'C'],
  payment_status: 'paid', status: 'active',
  authorized_at: '2026-07-04T10:00:00Z', warehouse_address: null,
  packages_released: null, package_unit: null, packages_balance: null,
  warehouse_name: null, warehouse_phone: null, is_on_credit: false,
  credit_granted_by_name: null, receipt_number: null,
  physical_document_number: null, packing_list_invoice_numbers: [],
  amount_paid_ngn: '0', balance_ngn: '0', total_ngn: '0', debt_due_date: null,
}

function renderPage(session: Session, note = NOTE) {
  vi.spyOn(rnModule.releaseNotesApi, 'get').mockResolvedValue(note)
  vi.spyOn(warehousesApi, 'list').mockResolvedValue([])
  vi.spyOn(usersApi, 'list').mockResolvedValue([])
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/release-notes/rn-001']}>
      <Routes>
        <Route
          path="/release-notes/:id"
          element={
            <SessionContext.Provider value={{ session, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }}>
              <ReleaseNoteDetail />
            </SessionContext.Provider>
          }
        />
      </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReleaseNoteDetail', () => {
  it('shows reference number', async () => {
    renderPage(WAREHOUSE_SESSION)
    expect((await screen.findAllByText('ACME-RN-20260704-0001')).length).toBeGreaterThan(0)
  })
  it('shows Record pickup button for warehouse on active note', async () => {
    renderPage(WAREHOUSE_SESSION)
    expect(await screen.findByRole('button', { name: /record pickup/i })).toBeTruthy()
  })
  it('does not show Record pickup for staff', async () => {
    renderPage(STAFF_SESSION)
    await screen.findAllByText('ACME-RN-20260704-0001')
    expect(screen.queryByRole('button', { name: /record pickup/i })).toBeNull()
  })
  it('shows Split note for staff on active note with multiple tags', async () => {
    renderPage(STAFF_SESSION)
    await userEvent.click(await screen.findByRole('button', { name: 'More release note actions' }))
    expect(screen.getByRole('menuitem', { name: /split note/i })).toBeTruthy()
  })
  it('shows no action buttons on picked_up note', async () => {
    renderPage(WAREHOUSE_SESSION, { ...NOTE, status: 'picked_up' })
    await screen.findAllByText('ACME-RN-20260704-0001')
    expect(screen.queryByRole('button', { name: /record pickup/i })).toBeNull()
  })

  it('sends collected_by_name on a non-delegate pickup, defaulted to the customer', async () => {
    // Regression: RecordPickupRequest requires collected_by_name when
    // is_delegate is false (a backend-side fix, per its own docstring) — but
    // nothing on this form ever collected or sent it, so every non-delegate
    // pickup (the common case: the customer collects in person) crashed.
    const recordPickup = vi.spyOn(rnModule.releaseNotesApi, 'recordPickup')
      .mockResolvedValue({
        release_note_id: NOTE.id, release_note_status: 'picked_up', pickup_record_id: 'pr-1',
        pickup_date: '2026-09-06', pickup_time: '10:00', attendant_name: 'Tunde',
        customer_service_officer_name: null, accounting_officer_name: null,
        remaining_cartons: 0, shipment_status: null,
      })
    renderPage(WAREHOUSE_SESSION)

    await userEvent.click(await screen.findByRole('button', { name: /record pickup/i }))
    const collectedByField = await screen.findByRole('textbox', { name: /^collected by$/i })
    // Defaults to the note's own customer — the common case — rather than
    // starting blank and forcing staff to retype a name they already see on
    // screen.
    expect(collectedByField).toHaveValue('Chioma Eze')

    await userEvent.click(screen.getByRole('button', { name: /confirm pickup/i }))

    await waitFor(() => expect(recordPickup).toHaveBeenCalledWith(
      'rn-001',
      expect.objectContaining({ collected_by_name: 'Chioma Eze' }),
    ))
  })

  it('disables Confirm pickup when the non-delegate collector name is cleared', async () => {
    renderPage(WAREHOUSE_SESSION)
    await userEvent.click(await screen.findByRole('button', { name: /record pickup/i }))

    const collectedByField = await screen.findByRole('textbox', { name: /^collected by$/i })
    await userEvent.clear(collectedByField)

    expect(screen.getByRole('button', { name: /confirm pickup/i })).toBeDisabled()
  })
})

describe('ReleaseNoteDetail pickup code (UX-09)', () => {
  const RESULT = {
  release_note_id: 'rn-001', release_note_status: 'picked_up' as const, pickup_record_id: 'pr-1',
  pickup_date: '2026-11-16', pickup_time: '10:00', attendant_name: 'Tunde',
  customer_service_officer_name: null, accounting_officer_name: null,
  remaining_cartons: 0, shipment_status: null,
}

  it('asks the warehouse for the code on a note that needs one and sends it', async () => {
    const recordPickup = vi.spyOn(rnModule.releaseNotesApi, 'recordPickup').mockResolvedValue(RESULT)
    renderPage(WAREHOUSE_SESSION, { ...NOTE, pickup_code_required: true })
    await userEvent.click(await screen.findByRole('button', { name: /record pickup/i }))
    const confirm = await screen.findByRole('button', { name: /confirm pickup/i })
    expect(confirm).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Pickup code/), '048213')
    await userEvent.click(confirm)
    await waitFor(() => expect(recordPickup).toHaveBeenCalledWith('rn-001', expect.objectContaining({ pickup_code: '048213' })))
  })

  it('asks for no code on a note without one', async () => {
    renderPage(WAREHOUSE_SESSION)
    await userEvent.click(await screen.findByRole('button', { name: /record pickup/i }))
    await screen.findByRole('button', { name: /confirm pickup/i })
    expect(screen.queryByLabelText(/Pickup code/)).toBeNull()
  })

  it('lets office staff send the customer a new code, and says where it went, never what it is', async () => {
    const send = vi.spyOn(rnModule.releaseNotesApi, 'sendPickupCode').mockResolvedValue({ release_note_id: 'rn-001', sent_via: ['sms', 'email'] })
    renderPage(STAFF_SESSION, { ...NOTE, pickup_code_required: true })
    await userEvent.click(await screen.findByRole('button', { name: 'Send new pickup code' }))
    const dialog = await screen.findByRole('dialog', { name: 'Send a new pickup code' })
    expect(dialog).toHaveTextContent('The code they have now will stop working.')
    await userEvent.click(screen.getByRole('button', { name: 'Send new code' }))
    await waitFor(() => expect(send).toHaveBeenCalledWith('rn-001'))
    expect(await screen.findByText('New pickup code sent')).toBeInTheDocument()
    expect(screen.getByText(/by SMS and email/)).toBeInTheDocument()
  })

  it('shows why a new code could not be sent', async () => {
    vi.spyOn(rnModule.releaseNotesApi, 'sendPickupCode').mockRejectedValue(
      new ApiError(
        { type: 'about:blank', title: 'Unprocessable Entity', status: 422, detail: 'The new pickup code could not be sent: the customer has no phone or email on file, or those channels are switched off', error_code: 'BUSINESS_RULE_VIOLATION', rule_id: 'PICKUP_CODE_NOT_DELIVERABLE' },
        null,
      ),
    )
    renderPage(STAFF_SESSION, { ...NOTE, pickup_code_required: true })
    await userEvent.click(await screen.findByRole('button', { name: 'Send new pickup code' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Send new code' }))
    expect(await screen.findByText(/no phone or email on file/)).toBeInTheDocument()
    expect(screen.queryByText('New pickup code sent')).toBeNull()
  })

  it('tells office staff when wrong codes have locked the note', async () => {
    renderPage(STAFF_SESSION, { ...NOTE, pickup_code_required: true, pickup_code_locked: true })
    expect(await screen.findByText('Pickup code locked')).toBeInTheDocument()
  })

  it('does not offer the warehouse a way to send codes', async () => {
    renderPage(WAREHOUSE_SESSION, { ...NOTE, pickup_code_required: true })
    await screen.findByRole('button', { name: /record pickup/i })
    expect(screen.queryByRole('button', { name: /Send (new )?pickup code/ })).toBeNull()
  })

  it('does not offer it on a note that is no longer active', async () => {
    renderPage(STAFF_SESSION, { ...NOTE, status: 'picked_up' })
    await screen.findByRole('heading', { name: 'Release note ACME-RN-20260704-0001' })
    expect(screen.queryByRole('button', { name: /Send (new )?pickup code/ })).toBeNull()
  })
})

