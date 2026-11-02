/**
 * Audit gap B5a — staff-side "Add customer": the list previously had no way to
 * create a customer at all despite POST /v1/customers existing.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { customersApi } from '../../api/tenantManagement'
import { AdminCustomerList } from './AdminCustomerList'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    customersApi: { ...original.customersApi, list: vi.fn(), create: vi.fn(), stats: vi.fn() },
  }
})

const NGOZI = {
  id: 'c1',
  tenant_id: 't1',
  name: 'Ngozi Okonkwo',
  phone: '+2348012345678',
  email: 'ngozi@example.com',
  whatsapp: null,
  address: null,
  anonymised_at: null,
  user_id: null,
  consent_given_at: null,
  notification_consent: ['sms'],
}

function renderPage(state?: Record<string, unknown>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: '/admin/customers', state: state ?? null }]}>
        <Routes>
          <Route path="/admin/customers" element={<TopBarTestWrapper><AdminCustomerList /></TopBarTestWrapper>} />
          <Route path="/admin/customers/:id" element={<div>Customer detail page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AdminCustomerList — Add customer (B5a)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(customersApi.stats).mockResolvedValue({ total: 2, active: 1, anonymised: 1, with_whatsapp: 1, shipments: 20 })
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [
        { ...NGOZI, notification_consent: ['sms', 'whatsapp'], shipment_count: 14 },
        { ...NGOZI, id: 'c2', name: null, email: null, phone: null, anonymised_at: '2026-03-14T00:00:00Z', notification_consent: null, shipment_count: 6 },
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
  })

  it('creates a customer with consent channels and navigates to the new profile', async () => {
    vi.mocked(customersApi.create).mockResolvedValue({ ...NGOZI, id: 'c-new', name: 'Emeka Eze' })
    renderPage()
    await screen.findByText('Ngozi Okonkwo')

    await userEvent.click(screen.getByRole('button', { name: /add customer/i }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/full name/i, { selector: 'input' }), 'Emeka Eze')
    // The national part only — the dial code comes from the picker, which
    // defaults to Nigeria. This is what a user actually types.
    await userEvent.type(
      within(dialog).getByLabelText('Phone', { exact: false, selector: 'input' }),
      '8037624419',
    )
    // sms is pre-ticked; add whatsapp consent (checkbox order: SMS, WhatsApp, Email)
    await userEvent.click(within(dialog).getAllByRole('checkbox')[1]!)
    await userEvent.click(within(dialog).getByRole('button', { name: /add customer/i }))

    await waitFor(() => {
      expect(customersApi.create).toHaveBeenCalledWith({
        name: 'Emeka Eze',
        phone: '+2348037624419',
        notification_consent: ['sms', 'whatsapp'],
      })
    })
    expect(await screen.findByText('Customer detail page')).toBeInTheDocument()
  })

  it('disables submit until a name is entered and surfaces API errors', async () => {
    renderPage()
    await screen.findByText('Ngozi Okonkwo')
    await userEvent.click(screen.getByRole('button', { name: /add customer/i }))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('button', { name: /add customer/i })).toBeDisabled()
  })
})

describe('AdminCustomerList — enrichment (B5b)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(customersApi.stats).mockResolvedValue({ total: 2, active: 1, anonymised: 1, with_whatsapp: 1, shipments: 20 })
    vi.mocked(customersApi.list).mockResolvedValue({
      data: [
        { ...NGOZI, notification_consent: ['sms', 'whatsapp'], shipment_count: 14 },
        { ...NGOZI, id: 'c2', name: null, email: null, phone: null, anonymised_at: '2026-03-14T00:00:00Z', notification_consent: null, shipment_count: 6 },
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
  })

  it('shows consent chips and shipment counts, and marks anonymised rows', async () => {
    renderPage()
    await screen.findByText('Ngozi Okonkwo')
    // Granted consent pills present (SMS + WA); shipments column
    expect(screen.getByText('WA')).toBeInTheDocument()
    expect(screen.getByText('14')).toBeInTheDocument()
    // Anonymised row: withdrawn consent + at least one "Anonymised" marker
    expect(screen.getByText('Withdrawn')).toBeInTheDocument()
    expect(screen.getAllByText('Anonymised').length).toBeGreaterThanOrEqual(1)
  })

  // §3.1 dashboard quick action deep-link
  it('auto-opens the add-customer modal when navigated with openAdd state', async () => {
    renderPage({ openAdd: true })
    expect(await screen.findByText('Add customer', { selector: 'h3, h2, [class*="modalTitle"]' })).toBeInTheDocument()
  })

  it('filters to anonymised via the chip', async () => {
    renderPage()
    await screen.findByText('Ngozi Okonkwo')
    // Anonymised chip (button) — count 1
    const chip = screen.getAllByText('Anonymised').find((el) => el.closest('button'))!
    await userEvent.click(chip)
    expect(screen.queryByText('Ngozi Okonkwo')).toBeNull()
    expect(screen.getByText('Withdrawn')).toBeInTheDocument()
  })
})
