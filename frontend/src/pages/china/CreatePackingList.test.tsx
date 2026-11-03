import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { packingListApi, type PackingList } from '../../api/packingList'
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
  return render(
    <MemoryRouter>
      <CreatePackingList />
    </MemoryRouter>,
  )
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
    render(
      <MemoryRouter initialEntries={['/packing-lists/pl-draft/edit']}>
        <Routes>
          <Route path="/packing-lists/:id/edit" element={<CreatePackingList />} />
        </Routes>
      </MemoryRouter>,
    )
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
