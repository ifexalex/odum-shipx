/**
 * 10.2 / audit gap A3 — customer shipment detail zones: hero, tracking stepper,
 * my-cartons table, billing summary with pay CTA, file-a-claim prompt.
 *
 * Also regression-guards the data-flow fix: the page loads the customer's own
 * packing list by id (GET /v1/packing-lists/{id}) — its predecessor called
 * /v1/track/{code}, a route that doesn't exist anywhere, so every load 404'd.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { billingApi } from '../../api/billing'
import { packingListApi } from '../../api/packingList'
import { MyShipmentDetail } from './MyShipmentDetail'

vi.mock('../../api/packingList', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/packingList')>()
  return { ...original, packingListApi: { ...original.packingListApi, get: vi.fn() } }
})
vi.mock('../../api/billing', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/billing')>()
  return { ...original, billingApi: { ...original.billingApi, list: vi.fn() } }
})

const PL = {
  id: 'pl1',
  reference: 'PL-20260415-001',
  customer_id: 'c1',
  container_id: 'cont1',
  container_number: 'MSCU1234567',
  container_status: 'in_transit',
  status: 'approved',
  carton_count: 2,
  total_cbm: '0.051',
  created_at: '2026-04-10T11:42:00Z',
  items: [
    {
      id: 'i1', packing_list_id: 'pl1', description: 'Electronics (mixed)',
      weight_dispatch_kg: '12.8', weight_actual_kg: null, carton_tag: 'SHX-00001',
      tracking_code: null, cbm: '0.030', length_cm: null, width_cm: null, height_cm: null,
      received_date: null, declared_value_usd: null,
    },
    {
      id: 'i2', packing_list_id: 'pl1', description: 'Clothing (assorted)',
      weight_dispatch_kg: '8.5', weight_actual_kg: null, carton_tag: 'SHX-00002',
      tracking_code: null, cbm: '0.021', length_cm: null, width_cm: null, height_cm: null,
      received_date: null, declared_value_usd: null,
    },
  ],
}

const BILLING = {
  id: 'b1', invoice_number: 'BL-1', customer_id: 'c1', customer_name: null,
  container_id: 'cont1', container_number: 'MSCU1234567',
  total_cbm: '0.051', cbm_rate_usd: '45', dollar_rate: '1550',
  subtotal_usd: '47.5', subtotal_ngn: '73656', misc_fees: [], misc_fees_ngn: 23500,
  adjustments_ngn: '0', carryover_ngn: 0, storage_fees_ngn: 0,
  total_due_ngn: '100008', total_paid_ngn: '49352', outstanding_ngn: '50656',
  payment_status: 'partially_paid', released_with_outstanding: false,
  billed_at: null, payments: [], carryovers: [], _active_disputes: [],
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter initialEntries={['/my-shipments/pl1']}>
        <Routes>
          <Route path="/my-shipments/:code" element={<MyShipmentDetail />} />
          <Route path="/my-billing/:id" element={<div>Billing detail page</div>} />
          <Route path="/my-claims/new" element={<div>File claim wizard</div>} />
        </Routes>
      </MemoryRouter>,
    ),
  )
}

describe('MyShipmentDetail — zones (A3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(packingListApi.get).mockResolvedValue(PL as never)
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [BILLING],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
  })

  it('loads the packing list by id (not the dead /v1/track route)', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Shipment PL-20260415-001' })).toBeInTheDocument()
    expect(packingListApi.get).toHaveBeenCalledWith('pl1')
  })

  it('renders hero with status badge, the stepper hint, and the carton rows', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Shipment PL-20260415-001' })

    // Appears in the hero badge and again as a stepper stage label
    expect(screen.getAllByText('In transit').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/container is at sea/i)).toBeInTheDocument()

    // Cartons zone
    expect(screen.getByText('My cartons')).toBeInTheDocument()
    expect(screen.getByText('SHX-00001')).toBeInTheDocument()
    expect(screen.getByText('Electronics (mixed)')).toBeInTheDocument()
    // One compact row per carton (FD-27): weight and volume on the row's own line.
    expect(screen.getByRole('list', { name: 'Cartons' }).querySelectorAll('li')).toHaveLength(2)
    expect(screen.getByText(/0\.030 CBM/)).toBeInTheDocument()
  })

  it('shows the billing summary and routes the pay CTA to the billing detail', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Shipment PL-20260415-001' })

    await waitFor(() => expect(screen.getByText('₦50,656')).toBeInTheDocument())
    expect(screen.getByText('₦100,008')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /pay outstanding/i }))
    expect(await screen.findByText('Billing detail page')).toBeInTheDocument()
  })

  it('hides the pay CTA when nothing is outstanding', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [{ ...BILLING, outstanding_ngn: '0', total_paid_ngn: '100008', payment_status: 'paid' }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    renderPage()
    await screen.findByRole('heading', { name: 'Shipment PL-20260415-001' })

    // Total and Paid both read ₦100,008 when fully settled
    await waitFor(() => expect(screen.getAllByText('₦100,008').length).toBeGreaterThanOrEqual(2))
    expect(screen.queryByRole('button', { name: /pay outstanding/i })).toBeNull()
  })

  it('explains when no bill exists yet for the shipment', async () => {
    vi.mocked(billingApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    } as never)
    renderPage()
    await screen.findByRole('heading', { name: 'Shipment PL-20260415-001' })

    expect(await screen.findByText(/no bill yet for this shipment/i)).toBeInTheDocument()
  })

  it('file-a-claim prompt routes to the claim wizard', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Shipment PL-20260415-001' })

    await userEvent.click(screen.getByRole('button', { name: /file a claim/i }))
    expect(await screen.findByText('File claim wizard')).toBeInTheDocument()
  })
})
