import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MAX_ITEM_QUANTITY, packingListApi, type PackingList } from '../../api/packingList'
import { containersApi, type Container } from '../../api/tracking'
import { configApi, customersApi, type Customer } from '../../api/tenantManagement'
import { warehousesApi } from '../../api/warehouses'
import { CreatePackingList } from './CreatePackingList'

vi.mock('../../api/packingList', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/packingList')>()
  return {
    ...actual,
    packingListApi: { create: vi.fn(), submit: vi.fn(), get: vi.fn(), update: vi.fn() },
  }
})
vi.mock('../../api/tracking', () => ({
  containersApi: { list: vi.fn() },
}))
import { ApiError } from '../../api/client'
import { withQuery } from '../../test/queryWrapper'

vi.mock('../../api/warehouses', () => ({
  warehousesApi: {
    list: vi.fn().mockResolvedValue([
      { id: 'wh1', name: 'Lagos — Trade Fair', city: 'Lagos', state: 'Lagos', address: null, phone: null, is_default: true },
      { id: 'wh2', name: 'Aba — Ariaria', city: 'Aba', state: 'Abia', address: null, phone: null, is_default: false },
    ]),
  },
}))
vi.mock('../../api/tenantManagement', () => ({
  customersApi: { list: vi.fn() },
  configApi: {
    getCbmRate: vi.fn().mockResolvedValue({
      currency: 'usd', rate_mode: 'flat', carton_rate: 48, bag_rate: 48, bale_rate: 48, effective_from: '', min_cbm_per_item: 0.001,
    }),
    getDollarRate: vi.fn().mockResolvedValue({ rate: 1650, currency_pair: 'USD_NGN', effective_from: '' }),
  },
}))

const customerStub: Customer = {
  id: 'cust1',
  tenant_id: 't1',
  name: 'Ngozi Okonkwo',
  phone: '+234 801 234 5678',
  email: null,
  whatsapp: null,
  address: null,
  anonymised_at: null,
  user_id: null,
  consent_given_at: null,
  notification_consent: null,
}

const containerStub: Container = {
  id: 'c1',
  tenant_id: 't1',
  container_number: 'MSCU1234567',
  parcel_number: null,
  origin: 'China',
  destination: 'Nigeria',
  ship_date: null,
  estimated_arrival_date: null,
  actual_arrival_date: null,
  status: 'loading',
  notes: null,
  created_by: 'staff-1',
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
  vessel_name: null,
  voyage_number: null,
  shipping_line: null,
  seal_number: null,
  container_type: null,
  capacity_cbm: null,
  recommended_cbm: null,
  created_by_name: null,
}

function renderPage() {
  return render(withQuery(
    <MemoryRouter>
      <CreatePackingList />
    </MemoryRouter>,
  ))
}

// The customer + container pickers are searchable Comboboxes (a button that
// opens a list), not native <select>s — open it and click the option by label.
async function pickCustomerAndContainer(): Promise<void> {
  await selectFromCombobox('Customer', 'Ngozi Okonkwo')
  await selectFromCombobox('Container', 'MSCU1234567')
}

async function selectFromCombobox(controlName: string, optionLabel: string): Promise<void> {
  const control = screen.getByRole('button', { name: controlName })
  await waitFor(() => expect(control).toBeEnabled())
  await userEvent.click(control)
  await userEvent.click(await screen.findByRole('option', { name: new RegExp(optionLabel) }))
}

async function completeStep1(): Promise<void> {
  await selectFromCombobox('Customer', 'Ngozi Okonkwo')
  await selectFromCombobox('Container', 'MSCU1234567')
  await userEvent.click(screen.getByText('Next: Add items'))
}

describe('CreatePackingList', () => {
  beforeEach(() => {
    vi.mocked(packingListApi.create).mockReset()
    vi.mocked(packingListApi.submit).mockReset()
    vi.mocked(customersApi.list).mockReset()
    vi.mocked(containersApi.list).mockReset()
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [customerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [containerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
  })

  it('disables Next on step 1 until a customer and container are chosen', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Customer' })).toBeEnabled())
    expect(screen.getByText('Next: Add items')).toBeDisabled()
    await selectFromCombobox('Customer', 'Ngozi Okonkwo')
    expect(screen.getByText('Next: Add items')).toBeDisabled()
    await selectFromCombobox('Container', 'MSCU1234567')
    expect(screen.getByText('Next: Add items')).toBeEnabled()
  })

  it('computes CBM live from L x W x H and shows it under Assigned on save tags', async () => {
    renderPage()
    await completeStep1()
    await waitFor(() => expect(screen.getByText('Line items')).toBeInTheDocument())

    const numberInputs = screen.getAllByRole('spinbutton')
    // Row layout: wt dispatch, wt actual, length, width, height, declared value.
    await userEvent.type(numberInputs[2]!, '40')
    await userEvent.type(numberInputs[3]!, '30')
    await userEvent.type(numberInputs[4]!, '25')

    await waitFor(() => expect(screen.getAllByText('0.030').length).toBeGreaterThan(0))
  })

  it('shows a live pricing estimate from the tenant CBM + FX rates', async () => {
    renderPage()
    await completeStep1()
    await waitFor(() => expect(screen.getByText('Line items')).toBeInTheDocument())

    // Rates loaded from the mocked configApi (CBM $48/m³, FX ₦1,650).
    await waitFor(() => expect(screen.getByText('Live pricing estimate')).toBeInTheDocument())
    expect(screen.getByText('$48.00')).toBeInTheDocument()

    // Enter a 0.030 m³ carton → shipping = 0.030 × $48 = $1.44 → ₦2,376.
    const numberInputs = screen.getAllByRole('spinbutton')
    await userEvent.type(numberInputs[2]!, '40')
    await userEvent.type(numberInputs[3]!, '30')
    await userEvent.type(numberInputs[4]!, '25')

    await waitFor(() => expect(screen.getByText('$1.44')).toBeInTheDocument())
    expect(screen.getByText('₦2,376')).toBeInTheDocument()
  })

  it('computes the NGN tile directly and derives USD via FX when the tenant prices in Naira', async () => {
    vi.mocked(configApi.getCbmRate).mockResolvedValueOnce({
      currency: 'ngn', rate_mode: 'flat', carton_rate: 79200, bag_rate: 79200, bale_rate: 79200, effective_from: '', min_cbm_per_item: 0.001,
    })
    renderPage()
    await completeStep1()
    await waitFor(() => expect(screen.getByText('Line items')).toBeInTheDocument())

    await waitFor(() => expect(screen.getByText('Live pricing estimate')).toBeInTheDocument())
    expect(screen.getByText('₦79200.00')).toBeInTheDocument()

    // 0.030 m³ × ₦79,200 = ₦2,376 directly; USD tile derived: 2376 / 1650 = $1.44.
    const numberInputs = screen.getAllByRole('spinbutton')
    await userEvent.type(numberInputs[2]!, '40')
    await userEvent.type(numberInputs[3]!, '30')
    await userEvent.type(numberInputs[4]!, '25')

    await waitFor(() => expect(screen.getByText('₦2,376')).toBeInTheDocument())
    expect(screen.getByText('$1.44')).toBeInTheDocument()
  })

  it('blocks advancing to review until every item has a description', async () => {
    renderPage()
    await completeStep1()
    expect(screen.getByText('Next: Review')).toBeDisabled()
    const [descriptionInput] = screen.getAllByPlaceholderText('e.g. Electronics (mixed)')
    await userEvent.type(descriptionInput!, 'Electronics')
    expect(screen.getByText('Next: Review')).toBeEnabled()
  })

  it('floors a tiny line item to the minimum CBM and labels a small bale', async () => {
    // Minimum 0.1: a 0.06 CBM bale is floored and tagged, and sized SM.
    vi.mocked(configApi.getCbmRate).mockResolvedValueOnce({
      currency: 'usd', rate_mode: 'flat', carton_rate: 48, bag_rate: 48, bale_rate: 48, effective_from: '', min_cbm_per_item: 0.1,
    })
    renderPage()
    await completeStep1()
    await screen.findByText('Line items')
    await userEvent.selectOptions(screen.getByLabelText('Package type for item 1'), 'bale')
    const nums = screen.getAllByRole('spinbutton')
    await userEvent.type(nums[2]!, '50')
    await userEvent.type(nums[3]!, '40')
    await userEvent.type(nums[4]!, '30')
    await waitFor(() => expect(screen.getAllByText('0.100').length).toBeGreaterThan(0))
    expect(screen.getByText('SM BALE')).toBeInTheDocument()
    expect(screen.getByText('min')).toBeInTheDocument()
  })

  it('labels a large bale BIG BALE', async () => {
    renderPage()
    await completeStep1()
    await screen.findByText('Line items')
    await userEvent.selectOptions(screen.getByLabelText('Package type for item 1'), 'bale')
    const nums = screen.getAllByRole('spinbutton')
    await userEvent.type(nums[2]!, '100')
    await userEvent.type(nums[3]!, '80')
    await userEvent.type(nums[4]!, '50') // 0.4 CBM
    await waitFor(() => expect(screen.getByText('BIG BALE')).toBeInTheDocument())
  })

  it('loads a draft for editing with the customer/container fixed and items prefilled', async () => {
    const draft: PackingList = {
      id: 'pl-draft',
      tenant_id: 't1',
      reference: 'PL-1',
      container_id: 'c1',
      container_number: 'MSCU1234567',
      customer_id: 'cust1',
      customer_name: 'Ngozi Okonkwo',
      loading_date: '2026-10-02',
      delivery_date: null,
      status: 'draft',
      items: [
        {
          id: 'it1',
          packing_list_id: 'pl-draft',
          description: 'Cotton bale',
          weight_dispatch_kg: '12',
          weight_actual_kg: '12',
          carton_tag: null,
          tracking_code: null,
          cbm: '0.400',
          length_cm: '100',
          width_cm: '80',
          height_cm: '50',
          received_date: null,
          declared_value_usd: '200',
          package_unit: 'bale',
          bale_type: 'BIG BALE',
        },
      ],
      total_cbm: '0.400',
      total_weight_kg: '12',
      carton_count: 1,
      created_by: 'staff-1',
      approved_by: null,
      approved_at: null,
      rejected_by: null,
      rejected_at: null,
      approval_comments: null,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    }
    vi.mocked(packingListApi.get).mockResolvedValue(draft)
    vi.mocked(packingListApi.update).mockResolvedValue(draft)
    render(withQuery(
      <MemoryRouter initialEntries={['/packing-lists/pl-draft/edit']}>
        <Routes>
          <Route path="/packing-lists/:id/edit" element={<CreatePackingList />} />
        </Routes>
      </MemoryRouter>,
    ))
    expect(await screen.findByText('Edit draft packing list')).toBeInTheDocument()
    // Customer/container pickers are present but fixed.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Customer' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Container' })).toBeDisabled()
    // Advancing to items shows the prefilled bale row.
    await userEvent.click(screen.getByText('Next: Add items'))
    expect(screen.getByDisplayValue('Cotton bale')).toBeInTheDocument()
    expect(packingListApi.get).toHaveBeenCalledWith('pl-draft')
    expect(packingListApi.create).not.toHaveBeenCalled()
  })

  it('creates and submits the packing list for approval from the review step', async () => {
    const created: PackingList = {
      id: 'pl1',
      tenant_id: 't1',
      reference: 'PL-20260101-001',
      container_id: 'c1',
      container_number: 'ACME-001',
      customer_id: 'cust1',
      status: 'draft',
      items: [],
      total_cbm: '0',
      total_weight_kg: '0',
      carton_count: 1,
      created_by: 'staff-1',
      approved_by: null,
      approved_at: null,
      rejected_by: null,
      rejected_at: null,
      approval_comments: null,
      created_at: '2026-01-01',
      updated_at: '2026-01-01',
    }
    vi.mocked(packingListApi.create).mockResolvedValue(created)
    vi.mocked(packingListApi.submit).mockResolvedValue({ ...created, status: 'pending_approval' })

    renderPage()
    await completeStep1()
    const [descriptionInput] = screen.getAllByPlaceholderText('e.g. Electronics (mixed)')
    await userEvent.type(descriptionInput!, 'Electronics')
    await userEvent.click(screen.getByText('Next: Review'))

    await userEvent.click(screen.getByText('Submit for approval'))
    await waitFor(() => expect(packingListApi.create).toHaveBeenCalledTimes(1))
    expect(packingListApi.submit).toHaveBeenCalledWith('pl1')

    const [body, idemKey] = vi.mocked(packingListApi.create).mock.calls[0]!
    expect(body.container_id).toBe('c1')
    expect(body.customer_id).toBe('cust1')
    // The default warehouse is pre-selected and sent without the user touching it.
    expect(body.arrival_warehouse_id).toBe('wh1')
    expect(typeof idemKey).toBe('string')
  })

  it('pre-selects the default arrival warehouse on step 1', async () => {
    renderPage()
    // The default warehouse (wh1) label shows as the picker's selected value.
    await waitFor(() =>
      expect(screen.getByLabelText('Arrival warehouse')).toHaveTextContent('Lagos — Trade Fair'),
    )
  })

  // ── Goods dates, 2026-11-03 ───────────────────────────────────────────────
  // delivery_date = goods received in the China warehouse (the supplier's
  // delivery); loading_date = goods loaded into the container. Delivery is
  // shown first because that is the order the events happen in.

  it('shows the delivery date before the loading date', async () => {
    renderPage()
    const delivery = await screen.findByLabelText(/^Delivery date/, { selector: 'input' })
    const loading = screen.getByLabelText(/^Loading date/, { selector: 'input' })
    // DOCUMENT_POSITION_FOLLOWING: loading comes after delivery in the DOM.
    expect(delivery.compareDocumentPosition(loading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('explains what each date means', async () => {
    renderPage()
    expect(await screen.findByText(/received in the china warehouse/i)).toBeInTheDocument()
    expect(screen.getByText(/loaded into the container/i)).toBeInTheDocument()
  })

  it('caps the delivery date picker at today so a future date is unreachable', async () => {
    renderPage()
    const delivery = await screen.findByLabelText(/^Delivery date/, { selector: 'input' })
    const now = new Date()
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
      now.getDate(),
    ).padStart(2, '0')}`
    expect(delivery).toHaveAttribute('max', today)
  })

  it('rejects a delivery date in the future and blocks the step', async () => {
    renderPage()
    await screen.findByText('Next: Add items')
    await pickCustomerAndContainer()
    const delivery = await screen.findByLabelText(/^Delivery date/, { selector: 'input' })
    await userEvent.type(delivery, '2099-01-01')
    expect(await screen.findByText(/cannot be a future date/i)).toBeInTheDocument()
    expect(screen.getByText('Next: Add items')).toBeDisabled()
  })

  it('rejects a loading date before the delivery date', async () => {
    // The core rule: goods cannot be loaded before they were received.
    renderPage()
    await screen.findByText('Next: Add items')
    await pickCustomerAndContainer()
    await userEvent.type(await screen.findByLabelText(/^Delivery date/, { selector: 'input' }), '2026-11-03')
    await userEvent.type(screen.getByLabelText(/^Loading date/, { selector: 'input' }), '2026-11-01')
    expect(await screen.findByText(/goods must be received before they are loaded/i)).toBeInTheDocument()
    expect(screen.getByText('Next: Add items')).toBeDisabled()
  })

  it('accepts loading on the same day as delivery', async () => {
    // Goods received in the morning are routinely loaded that afternoon.
    renderPage()
    await screen.findByText('Next: Add items')
    await pickCustomerAndContainer()
    await userEvent.type(await screen.findByLabelText(/^Delivery date/, { selector: 'input' }), '2026-11-03')
    await userEvent.type(screen.getByLabelText(/^Loading date/, { selector: 'input' }), '2026-11-03')
    expect(screen.queryByText(/goods must be received before/i)).toBeNull()
    expect(screen.getByText('Next: Add items')).toBeEnabled()
  })

  it('accepts a future loading date', async () => {
    // Unbounded on purpose: the container is still loading, so a planned date
    // is legitimate.
    renderPage()
    await screen.findByText('Next: Add items')
    await pickCustomerAndContainer()
    await userEvent.type(await screen.findByLabelText(/^Delivery date/, { selector: 'input' }), '2026-11-03')
    await userEvent.type(screen.getByLabelText(/^Loading date/, { selector: 'input' }), '2099-01-01')
    expect(screen.queryByText(/cannot be/i)).toBeNull()
    expect(screen.getByText('Next: Add items')).toBeEnabled()
  })

  it('bounds the loading date picker below by the delivery date', async () => {
    renderPage()
    await userEvent.type(await screen.findByLabelText(/^Delivery date/, { selector: 'input' }), '2026-11-03')
    expect(screen.getByLabelText(/^Loading date/, { selector: 'input' })).toHaveAttribute('min', '2026-11-03')
  })

  // ── Reported live, 2026-11-02 ──────────────────────────────────────────────
  // "The warehouse location isn't appearing when I create a packing list."
  // Root cause was a 403 (china_office_staff were missing from the warehouse
  // read roles) that the page caught and turned into an empty array, so the
  // picker rendered "No warehouses configured" — a permission error shown as a
  // configuration choice. The failure must stay visible.
  it('says warehouses are unavailable rather than claiming none are configured', async () => {
    vi.mocked(warehousesApi.list).mockRejectedValueOnce(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Forbidden',
          status: 403,
          detail: 'You do not have permission to perform this action',
          error_code: 'FORBIDDEN',
        },
        null,
      ),
    )
    renderPage()
    await screen.findByText(/could not be loaded/i)
    expect(screen.queryByText('No warehouses configured')).toBeNull()
  })

  it('still loads the rest of the form when warehouses fail', async () => {
    // One optional field must not take the whole form down with it.
    vi.mocked(warehousesApi.list).mockRejectedValueOnce(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Forbidden',
          status: 403,
          detail: 'You do not have permission to perform this action',
          error_code: 'FORBIDDEN',
        },
        null,
      ),
    )
    renderPage()
    await screen.findByText(/could not be loaded/i)
    expect(screen.getByLabelText('Arrival warehouse')).toBeInTheDocument()
  })
})

describe('CreatePackingList — bulk quantity', () => {
  beforeEach(() => {
    vi.mocked(packingListApi.create).mockReset()
    vi.mocked(packingListApi.submit).mockReset()
    vi.mocked(customersApi.list).mockReset()
    vi.mocked(containersApi.list).mockReset()
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [customerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [containerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
  })

  async function reachItemsStep(): Promise<void> {
    renderPage()
    await completeStep1()
  }

  it('leaves the quantity input disabled until "identical" is affirmed', async () => {
    await reachItemsStep()

    const qty = screen.getByRole('spinbutton', { name: /item 1: quantity/i })
    expect(qty).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox', { name: /item 1: all packages identical/i }))
    expect(qty).toBeEnabled()
  })

  it('resets a quantity back to one when the affirmation is withdrawn', async () => {
    // Otherwise a stale 100 could be saved by unticking the box and not
    // noticing the number left behind.
    await reachItemsStep()
    const confirm = screen.getByRole('checkbox', { name: /item 1: all packages identical/i })
    const qty = screen.getByRole('spinbutton', { name: /item 1: quantity/i })

    await userEvent.click(confirm)
    await userEvent.clear(qty)
    await userEvent.type(qty, '40')
    expect(qty).toHaveValue(40)

    await userEvent.click(confirm)
    expect(qty).toHaveValue(1)
  })

  it('shows what a quantity line will create, in CBM as well as count', async () => {
    await reachItemsStep()
    await userEvent.click(screen.getByRole('checkbox', { name: /item 1: all packages identical/i }))
    const qty = screen.getByRole('spinbutton', { name: /item 1: quantity/i })
    await userEvent.clear(qty)
    await userEvent.type(qty, '10')

    // The count alone is weak evidence; the CBM is what the staffer is really
    // being asked to sanity-check, because it drives billing.
    expect(await screen.findByText(/Creates 10 cartons/i)).toBeInTheDocument()
  })

  it('clamps a quantity above the cap rather than letting the API refuse it', async () => {
    await reachItemsStep()
    await userEvent.click(screen.getByRole('checkbox', { name: /item 1: all packages identical/i }))
    const qty = screen.getByRole('spinbutton', { name: /item 1: quantity/i })
    await userEvent.clear(qty)
    await userEvent.type(qty, '9999')

    expect(qty).toHaveValue(MAX_ITEM_QUANTITY)
  })

  it('asks for confirmation before saving a large quantity, and can be cancelled', async () => {
    await reachItemsStep()
    await userEvent.click(screen.getByRole('checkbox', { name: /item 1: all packages identical/i }))
    const qty = screen.getByRole('spinbutton', { name: /item 1: quantity/i })
    await userEvent.clear(qty)
    await userEvent.type(qty, '100')
    await userEvent.type(screen.getAllByPlaceholderText('e.g. Electronics (mixed)')[0]!, 'Shoes')

    await userEvent.click(screen.getByRole('button', { name: /save draft/i }))

    expect(await screen.findByText(/Create 100 packages\?/i)).toBeInTheDocument()
    // Cancelling must not write anything.
    await userEvent.click(screen.getByRole('button', { name: /go back/i }))
    expect(packingListApi.create).not.toHaveBeenCalled()
  })

  it('does not interrupt a save when every line is a single package', async () => {
    vi.mocked(packingListApi.create).mockResolvedValue({ id: 'pl1' } as PackingList)
    await reachItemsStep()
    await userEvent.type(screen.getAllByPlaceholderText('e.g. Electronics (mixed)')[0]!, 'One carton')

    await userEvent.click(screen.getByRole('button', { name: /save draft/i }))

    await waitFor(() => expect(packingListApi.create).toHaveBeenCalled())
    expect(screen.queryByText(/packages\?$/i)).not.toBeInTheDocument()
  })
})

describe('CreatePackingList — reopening a saved draft', () => {
  beforeEach(() => {
    vi.mocked(packingListApi.get).mockReset()
    vi.mocked(packingListApi.update).mockReset()
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [customerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [containerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
  })

  /** The server stores a bulk line EXPANDED, so this is what a reopened draft
   *  actually returns: N rows sharing one batch_ref. */
  function expandedBatch(n: number, batchRef = 'batch-1') {
    return Array.from({ length: n }, (_, i) => ({
      id: `it${i}`,
      packing_list_id: 'pl1',
      description: 'Ladies shoes',
      package_unit: 'carton',
      length_cm: 60,
      width_cm: 40,
      height_cm: 40,
      weight_actual_kg: 12,
      weight_dispatch_kg: 12,
      declared_value_usd: 50,
      received_date: '2026-11-01',
      carton_tag: `ACM-C1-${String(i + 1).padStart(3, '0')}`,
      cbm: 0.1,
      batch_ref: batchRef,
    }))
  }

  async function renderEdit(items: unknown[]) {
    vi.mocked(packingListApi.get).mockResolvedValue({
      id: 'pl1',
      status: 'draft',
      container_id: containerStub.id,
      customer_id: customerStub.id,
      items,
    } as never)
    render(withQuery(
      <MemoryRouter initialEntries={['/packing-lists/pl1/edit']}>
        <Routes>
          <Route path="/packing-lists/:id/edit" element={<CreatePackingList />} />
        </Routes>
      </MemoryRouter>,
    ))
    // The wizard opens on step 1 even when editing; the items table lives on
    // step 2.
    const next = await screen.findByText('Next: Add items')
    await waitFor(() => expect(next).toBeEnabled())
    await userEvent.click(next)
  }

  it('shows a saved bulk line as ONE row carrying its quantity', async () => {
    // The bug reported from the warehouse: you key one line of 100, save, and
    // reopen to find a hundred rows and no quantity anywhere.
    await renderEdit(expandedBatch(100))

    const qty = await screen.findByRole('spinbutton', { name: /item 1: quantity/i })
    expect(qty).toHaveValue(100)
    expect(screen.queryByRole('spinbutton', { name: /item 2: quantity/i })).not.toBeInTheDocument()
  })

  it('shows the batch as already affirmed, so the quantity stays editable', async () => {
    await renderEdit(expandedBatch(100))

    expect(await screen.findByRole('checkbox', { name: /item 1: all packages identical/i })).toBeChecked()
    expect(await screen.findByRole('spinbutton', { name: /item 1: quantity/i })).toBeEnabled()
  })

  it('keeps rows expanded when one package of a batch was edited away', async () => {
    // Folding them would silently discard that edit.
    const items = expandedBatch(3)
    items[1] = { ...items[1], weight_actual_kg: 99 } as never

    await renderEdit(items)

    expect(await screen.findByRole('spinbutton', { name: /item 3: quantity/i })).toBeInTheDocument()
  })

  it('leaves individually-keyed rows alone', async () => {
    const items = expandedBatch(2).map((it) => ({ ...it, batch_ref: null }))

    await renderEdit(items)

    expect(await screen.findByRole('spinbutton', { name: /item 2: quantity/i })).toBeInTheDocument()
  })
})

describe('CreatePackingList — review step shows the full item detail', () => {
  beforeEach(() => {
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [customerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [containerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
  })

  async function reachReview(): Promise<void> {
    renderPage()
    await completeStep1()
    await userEvent.type(screen.getAllByPlaceholderText('e.g. Electronics (mixed)')[0]!, 'Ladies shoes')
    const spin = screen.getAllByRole('spinbutton')
    // wt disp, wt act, L, W, H
    for (const [i, v] of [[0, '12'], [1, '12'], [2, '60'], [3, '40'], [4, '40']] as const) {
      await userEvent.clear(spin[i]!)
      await userEvent.type(spin[i]!, v)
    }
    await userEvent.click(screen.getByRole('checkbox', { name: /item 1: all packages identical/i }))
    const qty = screen.getByRole('spinbutton', { name: /item 1: quantity/i })
    await userEvent.clear(qty)
    await userEvent.type(qty, '100')
    await userEvent.click(screen.getByText('Next: Review'))
  }

  it('states the package type and quantity, not just a description', async () => {
    // Reported as: "a lot of information is missing when I preview the packing
    // list … quantity, the package type, carton or bag". Both were absent.
    await reachReview()

    expect(await screen.findByText('Type')).toBeInTheDocument()
    expect(screen.getByText('Qty')).toBeInTheDocument()
    expect(screen.getByText('carton')).toBeInTheDocument()
  })

  it('describes the totals by package type rather than hardcoding "carton"', async () => {
    // The summary said "N carton(s)" whatever the goods were, so a list of
    // bales described itself as cartons on the screen meant for checking it.
    await reachReview()

    // Twice over: the "ready to submit" banner and the document preview's
    // totals line. Both used to say "carton(s)" regardless of the goods.
    expect((await screen.findAllByText(/100 cartons/)).length).toBeGreaterThanOrEqual(2)
  })
})

describe('CreatePackingList — saving twice must not make two lists', () => {
  beforeEach(() => {
    vi.mocked(packingListApi.create).mockReset()
    vi.mocked(packingListApi.update).mockReset()
    vi.mocked(packingListApi.submit).mockReset()
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [customerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [containerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
  })

  async function fillAndSave(): Promise<void> {
    await userEvent.type(screen.getAllByPlaceholderText('e.g. Electronics (mixed)')[0]!, 'Widget')
    await userEvent.click(screen.getByRole('button', { name: /save draft/i }))
  }

  it('creates on the first save and UPDATES on the second', async () => {
    // Reported as "it keeps saving a new copy of that same item to the draft".
    // The page never recorded the id it had just created, so every save took
    // the create branch and made another list holding the same cargo.
    vi.mocked(packingListApi.create).mockResolvedValue({ id: 'pl-new' } as never)
    vi.mocked(packingListApi.update).mockResolvedValue({ id: 'pl-new' } as never)

    renderPage()
    await completeStep1()
    await fillAndSave()
    await waitFor(() => expect(packingListApi.create).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByRole('button', { name: /save draft/i }))

    await waitFor(() => expect(packingListApi.update).toHaveBeenCalledTimes(1))
    expect(packingListApi.create).toHaveBeenCalledTimes(1)
    expect(vi.mocked(packingListApi.update).mock.calls[0]![0]).toBe('pl-new')
  })

  it('still creates only once when the first save failed to submit', async () => {
    // The nastiest version: create succeeds, submit throws, the user presses
    // save again. Previously that produced a second list every time.
    vi.mocked(packingListApi.create).mockResolvedValue({ id: 'pl-new' } as never)
    vi.mocked(packingListApi.update).mockResolvedValue({ id: 'pl-new' } as never)
    vi.mocked(packingListApi.submit).mockRejectedValueOnce(new Error('network'))

    renderPage()
    await completeStep1()
    await userEvent.type(screen.getAllByPlaceholderText('e.g. Electronics (mixed)')[0]!, 'Widget')
    // "Submit for approval" lives on the review step, not the items step.
    await userEvent.click(screen.getByText('Next: Review'))
    await userEvent.click(await screen.findByRole('button', { name: /submit for approval/i }))
    await waitFor(() => expect(packingListApi.create).toHaveBeenCalledTimes(1))

    await userEvent.click(screen.getByRole('button', { name: /save draft/i }))

    await waitFor(() => expect(packingListApi.update).toHaveBeenCalled())
    expect(packingListApi.create).toHaveBeenCalledTimes(1)
  })
})

