import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { packingListApi, type PackingList } from '../../api/packingList'
import { containersApi, type Container } from '../../api/tracking'
import { configApi, customersApi, type Customer } from '../../api/tenantManagement'
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
    expect(typeof idemKey).toBe('string')
  })
})
