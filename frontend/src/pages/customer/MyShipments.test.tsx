/**
 * Regression guard for the 2026-09-06 fix: MyShipments used to render only
 * `activeShipments[0]` as a single "Active shipment" feature card, silently
 * dropping every other shipment a customer had in transit. Found live testing
 * an account with 3 simultaneously active shipments — only the first showed.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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
  return { ...original, billingApi: { ...original.billingApi, listForCustomer: vi.fn() } }
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
    <MemoryRouter>
      <MyShipments />
    </MemoryRouter>,
  )
}

describe('MyShipments — all active shipments render, not just the latest', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useSession).mockReturnValue({
      session: { userId: 'c1', name: 'Ify Ugwuoke' },
    } as never)
    vi.mocked(billingApi.listForCustomer).mockResolvedValue([])
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
