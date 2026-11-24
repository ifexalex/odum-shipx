import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { withQuery } from '../../test/queryWrapper'
import * as rnModule from '../../api/releaseNotes'
import type { ReleaseNote, ReleaseNoteListParams } from '../../api/releaseNotes'
import { SessionContext } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { WarehouseDashboard } from './WarehouseDashboard'

const SESSION: Session = {
  userId: 'u-wh', tenantId: 't-001', role: 'warehouse_attendant', roles: ['warehouse_attendant'],
  name: 'Tunde Bello', email: 'warehouse@test.com',
  isPlatformAdmin: false,
  impersonatedBy: null,
  sessionId: null,
  readOnly: false,
  expiresAt: Date.now() + 60_000,
  tokenType: 'cognito',
}

function note(overrides: Partial<ReleaseNote>): ReleaseNote {
  return {
    id: 'rn1', reference_number: 'RN-20260716-ABC123', customer_name: 'Ngozi Okonkwo',
    container_number: 'MSCU1234567', carton_count: 4, total_cartons_for_customer: 4,
    is_partial_release: false, carton_tags: [], payment_status: 'paid', status: 'active',
    authorized_at: new Date().toISOString(), warehouse_address: null,
    packages_released: null, package_unit: null, packages_balance: null,
    warehouse_name: null, warehouse_phone: null, is_on_credit: false,
    credit_granted_by_name: null, receipt_number: null,
    physical_document_number: null, packing_list_invoice_numbers: [],
    amount_paid_ngn: '0', balance_ngn: '0', total_ngn: '0', debt_due_date: null,
    ...overrides,
  }
}

function ok(notes: ReleaseNote[], hasMore = false) {
  return { data: notes, meta: { pagination: { has_more: hasMore, next_cursor: null, total_count: notes.length } } }
}

/** Route the 3 parallel list calls (active / picked_up / expired) by status. */
function mockLists({ active = [], pickedUp = [], expired = [] }: { active?: ReleaseNote[]; pickedUp?: ReleaseNote[]; expired?: ReleaseNote[] }) {
  return vi.spyOn(rnModule.releaseNotesApi, 'list').mockImplementation((params: ReleaseNoteListParams = {}) => {
    if (params.reference) return Promise.resolve(ok([]))
    if (params.status === 'picked_up') return Promise.resolve(ok(pickedUp))
    if (params.status === 'expired') return Promise.resolve(ok(expired))
    return Promise.resolve(ok(active))
  })
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter>
        <SessionContext.Provider value={{ session: SESSION, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }}>
          <Routes>
            <Route path="/" element={<WarehouseDashboard />} />
            <Route path="/release-notes/:id" element={<div>Release note detail</div>} />
          </Routes>
        </SessionContext.Provider>
      </MemoryRouter>,
    ),
  )
}

describe('WarehouseDashboard', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('is titled for its task, not the role the shell already names (FD-26)', () => {
    mockLists({})
    renderPage()
    expect(screen.getByRole('heading', { level: 1, name: 'Pickups' })).toBeInTheDocument()
  })

  it('shows empty state when queue is empty', async () => {
    mockLists({})
    renderPage()
    expect(await screen.findByText('All clear!')).toBeTruthy()
  })

  // P2-2 — real stats: completed-today counts picked_up notes with today's picked_up_at
  it('counts completed-today from picked_up notes and shows the expired backlog', async () => {
    mockLists({
      active: [note({})],
      pickedUp: [
        note({ id: 'p1', status: 'picked_up', picked_up_at: new Date().toISOString() }),
        note({ id: 'p2', status: 'picked_up', picked_up_at: new Date().toISOString() }),
        note({ id: 'p3', status: 'picked_up', picked_up_at: '2026-01-01T10:00:00Z' }), // not today
      ],
      expired: [
        note({ id: 'e1', status: 'expired' }),
        note({ id: 'e2', status: 'expired' }),
        note({ id: 'e3', status: 'expired' }),
      ],
    })
    renderPage()

    await waitFor(() => expect(screen.getByText('Completed today')).toBeInTheDocument())
    // Distinct values: completed today = 2 (only today's pickups), expired = 3.
    // These are `find*` rather than `get*` because the three status lists are
    // now three independent queries (7.150) instead of one Promise.all, so the
    // labels can paint a tick before their counts do.
    expect(await screen.findByText('2')).toBeInTheDocument()
    expect(await screen.findByText('3')).toBeInTheDocument()
    expect(screen.getByText('Expired · not collected')).toBeInTheDocument()
  })

  // P2-2 — urgency: >24h-old notes get the Urgent chip
  it('flags notes older than 24h as urgent', async () => {
    mockLists({
      active: [note({ authorized_at: new Date(Date.now() - 26 * 3600_000).toISOString() })],
    })
    renderPage()

    await waitFor(() => expect(screen.getByText('Waiting 24h+')).toBeInTheDocument())
    expect(screen.getByText(/1 urgent · 24h\+ old/)).toBeInTheDocument()
  })

  it('shows no chip on a note that is not urgent (FD-26)', async () => {
    mockLists({ active: [note({})] })
    renderPage()
    await screen.findByRole('button', { name: 'Record pickup' })
    expect(screen.queryByText('Waiting 24h+')).toBeNull()
    expect(screen.queryByText('New')).toBeNull()
  })

  // P2-2 — scan-or-type lookup: active match opens the pickup sheet directly
  it('opens the pickup sheet when a typed reference matches an active note', async () => {
    mockLists({ active: [note({})] })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Release note reference')).toBeInTheDocument())

    await userEvent.type(screen.getByLabelText('Release note reference'), 'rn-20260716-abc123{Enter}')

    // Pickup sheet opens (Confirm pickup button is its unique CTA)
    expect(await screen.findByRole('button', { name: /Confirm pickup/ })).toBeInTheDocument()
  })

  it('shows an inline error when the reference matches nothing', async () => {
    mockLists({ active: [note({})] })
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Release note reference')).toBeInTheDocument())

    await userEvent.type(screen.getByLabelText('Release note reference'), 'RN-NOPE{Enter}')

    expect(await screen.findByText(/No release note found for "RN-NOPE"/)).toBeInTheDocument()
  })
})

describe('WarehouseDashboard pickup sheet (UX-09)', () => {
  beforeEach(() => vi.restoreAllMocks())

  const RESULT = {
  release_note_id: 'rn1', release_note_status: 'picked_up' as const, pickup_record_id: 'pr-1',
  pickup_date: '2026-11-16', pickup_time: '10:00', attendant_name: 'Tunde',
  customer_service_officer_name: null, accounting_officer_name: null,
  remaining_cartons: 0, shipment_status: null,
}

  async function openSheet(overrides: Partial<ReleaseNote> = {}) {
    mockLists({ active: [note(overrides)] })
    const recordPickup = vi.spyOn(rnModule.releaseNotesApi, 'recordPickup').mockResolvedValue(RESULT)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Record pickup' }))
    await screen.findByRole('button', { name: /Confirm pickup/ })
    return recordPickup
  }

  it('sends the collector name for an in-person pickup, defaulted to the customer', async () => {
    // Regression: this sheet sent only the carton count, and the backend requires collected_by_name when it is
    // not a delegate pickup, so every in-person pickup recorded from the dashboard was refused.
    const recordPickup = await openSheet()
    expect(screen.getByLabelText(/^Collected by/)).toHaveValue('Ngozi Okonkwo')
    await userEvent.click(screen.getByRole('button', { name: /Confirm pickup/ }))
    await waitFor(() => expect(recordPickup).toHaveBeenCalledWith('rn1', { cartons_released: 4, collected_by_name: 'Ngozi Okonkwo' }))
  })

  it('cannot be confirmed with no collector name', async () => {
    await openSheet()
    await userEvent.clear(screen.getByLabelText(/^Collected by/))
    expect(screen.getByRole('button', { name: /Confirm pickup/ })).toBeDisabled()
  })

  it('asks for no code on a note that has none', async () => {
    await openSheet()
    expect(screen.queryByLabelText(/Pickup code/)).toBeNull()
  })

  it('asks for the pickup code when the note needs one, and will not confirm without it', async () => {
    await openSheet({ pickup_code_required: true })
    expect(screen.getByLabelText(/Pickup code/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Confirm pickup/ })).toBeDisabled()
  })

  it('sends the code the collector gave', async () => {
    const recordPickup = await openSheet({ pickup_code_required: true })
    await userEvent.type(screen.getByLabelText(/Pickup code/), '048 213')
    await userEvent.click(screen.getByRole('button', { name: /Confirm pickup/ }))
    await waitFor(() => expect(recordPickup).toHaveBeenCalledWith('rn1', expect.objectContaining({ pickup_code: '048 213' })))
  })

  it('shows the reason when the code is wrong, and stays open to try again', async () => {
    mockLists({ active: [note({ pickup_code_required: true })] })
    vi.spyOn(rnModule.releaseNotesApi, 'recordPickup').mockRejectedValue(
      new ApiError(
        { type: 'about:blank', title: 'Unprocessable Entity', status: 422, detail: 'That pickup code is not right. 4 tries left before this release note is locked.', error_code: 'BUSINESS_RULE_VIOLATION', rule_id: 'PICKUP_CODE_INVALID' },
        null,
      ),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Record pickup' }))
    await userEvent.type(await screen.findByLabelText(/Pickup code/), '999999')
    await userEvent.click(screen.getByRole('button', { name: /Confirm pickup/ }))
    expect(await screen.findByText(/That pickup code is not right. 4 tries left/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Pickup code/)).toBeInTheDocument()
  })

  it('says a locked note cannot be released and offers no code field', async () => {
    await openSheet({ pickup_code_required: true, pickup_code_locked: true })
    expect(screen.getByText('Pickup code locked')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Pickup code/)).toBeNull()
    expect(screen.getByRole('button', { name: /Confirm pickup/ })).toBeDisabled()
  })
})

describe('WarehouseDashboard at the counter: scanner and keyboard only (FD-26)', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('starts with the reference field focused', async () => {
    mockLists({})
    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Release note reference')).toHaveFocus())
  })

  it('records a pickup and is ready for the next scan with no click', async () => {
    mockLists({ active: [note({ pickup_code_required: true })] })
    const recordPickup = vi.spyOn(rnModule.releaseNotesApi, 'recordPickup').mockResolvedValue({
      release_note_id: 'rn1', release_note_status: 'picked_up', pickup_record_id: 'pr-1',
      pickup_date: '2026-11-16', pickup_time: '10:00', attendant_name: 'Tunde',
      customer_service_officer_name: null, accounting_officer_name: null,
      remaining_cartons: 0, shipment_status: null,
    })
    renderPage()
    await screen.findByRole('button', { name: 'Record pickup' })
    // The scanner types the reference and sends Enter.
    await userEvent.keyboard('RN-20260716-ABC123{Enter}')
    // The sheet opens on the code field; the collector reads the code out and Enter confirms.
    await waitFor(() => expect(screen.getByLabelText(/Pickup code/)).toHaveFocus())
    await userEvent.keyboard('048213{Enter}')
    await waitFor(() => expect(recordPickup).toHaveBeenCalledWith('rn1', expect.objectContaining({ pickup_code: '048213' })))
    expect(await screen.findByText('Pickup recorded')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Release note reference')).toHaveFocus())
    expect(screen.getByLabelText('Release note reference')).toHaveValue('')
  })

  it('says what is needed when Look up is pressed with nothing entered, instead of a disabled button', async () => {
    mockLists({})
    renderPage()
    const lookUp = screen.getByRole('button', { name: 'Look up' })
    expect(lookUp).toBeEnabled()
    await userEvent.click(lookUp)
    expect(await screen.findByText('Scan or type a release note reference first.')).toBeInTheDocument()
  })
})
