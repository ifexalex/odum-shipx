/**
 * Regression guard for the 2026-09-06 fix: MyShipments used to render only
 * `activeShipments[0]` as a single "Active shipment" feature card, silently
 * dropping every other shipment a customer had in transit. Found live testing
 * an account with 3 simultaneously active shipments — only the first showed.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { billingApi } from '../../api/billing'
import { packingListApi } from '../../api/packingList'
import { useSession } from '../../auth/useSession'
import { MyShipments } from './MyShipments'

vi.mock('../../api/packingList', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/packingList')>()
  return { ...original, packingListApi: { ...original.packingListApi, list: vi.fn() } }
})
vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return { ...original, billingApi: { ...original.billingApi, list: vi.fn(), listForCustomer: vi.fn() } }
})
vi.mock('../../auth/useSession')

function shipment(id: string, reference: string, status: string) {
  return {
    id,
    reference,
    customer_id: 'c1',
    container_id: `cont-${id}`,
    container_number: `CONT-${id}`,
    container_status: status,
    status: 'approved',
    carton_count: 2,
    total_cbm: '0.051',
    created_at: '2026-09-01T11:42:00Z',
  }
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter>
        <MyShipments />
      </MemoryRouter>,
    ),
  )
}

describe('MyShipments — all active shipments render, not just the latest', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useSession).mockReturnValue({
      session: { userId: 'c1', name: 'Ify Ugwuoke' },
    } as never)
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    } as never)
  })

  // Regression guard for the 7.150 find: the billing half called
  // billingApi.listForCustomer(session.userId), but that endpoint takes a
  // *customer* id and the backend compares it against the customer row resolved
  // from the caller's user_id — so it returned 403 on every call (verified live
  // against the local stack). Promise.allSettled swallowed it and billing was
  // always [], so the outstanding-balance greeting silently always read zero.
  it('reads billing from the force-scoped list endpoint, never by user id', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [shipment('pl1', 'PL-001', 'sealed')],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [{ container_id: 'cont-pl1', outstanding_ngn: '50656' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)

    renderPage()

    // The outstanding total reaches the header, which it never could while
    // the request 403'd.
    expect(await screen.findByText(/₦[\d,]+ outstanding/)).toBeInTheDocument()
    expect(billingApi.list).toHaveBeenCalled()
    expect(billingApi.listForCustomer).not.toHaveBeenCalled()
  })

  it('renders a card for every active shipment, not just the first', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [
        shipment('pl1', 'PL-001', 'sealed'),
        shipment('pl2', 'PL-002', 'loading'),
        shipment('pl3', 'PL-003', 'in_transit'),
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 3 } },
    } as never)

    renderPage()

    expect(await screen.findByText('Active shipments (3)')).toBeInTheDocument()
    expect(screen.getByText('PL-001')).toBeInTheDocument()
    expect(screen.getByText('PL-002')).toBeInTheDocument()
    expect(screen.getByText('PL-003')).toBeInTheDocument()
  })

  it('uses the singular heading and copy for exactly one active shipment', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [shipment('pl1', 'PL-001', 'sealed')],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)

    renderPage()

    expect(await screen.findByText('Active shipment')).toBeInTheDocument()
    expect(screen.queryByText(/Active shipments \(/)).toBeNull()
  })
})

describe('MyShipments wording and emphasis (FD-27)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useSession).mockReturnValue({ session: { userId: 'c1', name: 'Ify Ugwuoke' } } as never)
  })

  function withShipments(rows: ReturnType<typeof shipment>[], billing: unknown[] = []) {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: rows,
      meta: { pagination: { has_more: false, next_cursor: null, total_count: rows.length } },
    } as never)
    vi.mocked(billingApi.list).mockResolvedValue({
      data: billing,
      meta: { pagination: { has_more: false, next_cursor: null, total_count: billing.length } },
    } as never)
  }

  it('counts shipments by stage, not all as on the way', async () => {
    withShipments([
      shipment('pl1', 'PL-001', 'in_transit'),
      shipment('pl2', 'PL-002', 'sealed'),
      shipment('pl3', 'PL-003', 'loading'),
      shipment('pl4', 'PL-004', 'at_warehouse'),
      shipment('pl5', 'PL-005', 'at_warehouse'),
    ])
    renderPage()
    expect(await screen.findByText('3 in transit, 2 ready for pickup')).toBeInTheDocument()
  })

  it('says Delayed, not a past expected date, for a shipment still at sea', async () => {
    withShipments([{ ...shipment('pl1', 'PL-001', 'in_transit'), container_eta: '2026-01-09' } as never])
    renderPage()
    expect(await screen.findByText('Delayed')).toBeInTheDocument()
    expect(screen.queryByText('Expected arrival')).toBeNull()
  })

  it('says Arrived once the container has reached Nigeria', async () => {
    withShipments([{ ...shipment('pl1', 'PL-001', 'at_warehouse'), container_eta: '2026-01-09' } as never])
    renderPage()
    expect(await screen.findByText('Arrived')).toBeInTheDocument()
    expect(screen.queryByText('Expected arrival')).toBeNull()
  })

  it('shows a future expected date as expected', async () => {
    withShipments([{ ...shipment('pl1', 'PL-001', 'in_transit'), container_eta: '2999-01-09' } as never])
    renderPage()
    expect(await screen.findByText('Expected arrival')).toBeInTheDocument()
  })

  it('opens the shipment from the card, with one link and no separate button', async () => {
    withShipments([shipment('pl1', 'PL-001', 'in_transit')])
    renderPage()
    const link = await screen.findByRole('link', { name: 'PL-001' })
    expect(link).toHaveAttribute('href', '/my-shipments/pl1')
    expect(screen.queryByRole('button', { name: /View details/ })).toBeNull()
  })

  it('sets the total in ink and only an amount owed in red', async () => {
    withShipments([shipment('pl1', 'PL-001', 'in_transit')], [
      { container_id: 'cont-pl1', total_due_ngn: '100000', outstanding_ngn: '40000' },
    ])
    renderPage()
    const owed = await screen.findByText('₦40,000')
    // jsdom does not resolve custom properties, so read the inline colour as written.
    expect(owed.getAttribute('style')).toContain('var(--color-error)')
    expect(screen.getByText('₦100,000').getAttribute('style')).toContain('var(--color-ink)')
  })
})
