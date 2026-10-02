/**
 * Printable release note — audited field-by-field against a real paper
 * "Goods Release Note" the user shared. Confirms the new fields render and
 * that the per-note warehouse address is used instead of the old tenant-wide
 * branding.warehouse_address singleton.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { releaseNotesApi, type ReleaseNote } from '../../api/releaseNotes'
import { configApi } from '../../api/tenantManagement'
import { PrintReleaseNote } from './PrintReleaseNote'

vi.mock('../../api/releaseNotes', () => ({
  releaseNotesApi: { get: vi.fn() },
}))

vi.mock('../../api/tenantManagement', async () => {
  const actual = await vi.importActual<typeof import('../../api/tenantManagement')>('../../api/tenantManagement')
  return { ...actual, configApi: { ...actual.configApi, getConfig: vi.fn() } }
})

function makeNote(overrides: Partial<ReleaseNote> = {}): ReleaseNote {
  return {
    id: 'note-001',
    reference_number: 'ACM-RN-20260913-0001',
    customer_name: 'Baba Sunny',
    container_number: 'ACME001001',
    carton_count: 5,
    total_cartons_for_customer: 5,
    is_partial_release: false,
    carton_tags: ['TAG-001', 'TAG-002'],
    packages_released: null,
    package_unit: null,
    packages_balance: 0,
    payment_status: 'paid',
    status: 'active',
    authorized_at: '2026-09-13T10:00:00Z',
    warehouse_address: null,
    warehouse_name: null,
    warehouse_phone: null,
    is_on_credit: false,
    credit_granted_by_name: null,
    receipt_number: null,
    physical_document_number: null,
    packing_list_invoice_numbers: [],
    amount_paid_ngn: '0',
    balance_ngn: '0',
    total_ngn: '0',
    debt_due_date: null,
    ...overrides,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/release-notes/note-001/print']}>
        <Routes>
          <Route path="/release-notes/:id/print" element={<PrintReleaseNote />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(releaseNotesApi.get).mockReset()
  vi.mocked(configApi.getConfig).mockReset().mockResolvedValue({
    branding_config: { warehouse_address: 'Fallback tenant-wide address' },
  } as never)
})

describe('PrintReleaseNote', () => {
  it('uses the note\'s own linked warehouse instead of the tenant-wide branding address', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(
      makeNote({ warehouse_name: 'Lagos Island', warehouse_address: '3rd Floor, Capital Plaza', warehouse_phone: '07066171191' }),
    )
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(screen.getByText(/Lagos Island/)).toBeInTheDocument()
    expect(screen.getByText(/3rd Floor, Capital Plaza/)).toBeInTheDocument()
    expect(screen.queryByText(/Fallback tenant-wide address/)).toBeNull()
  })

  it('falls back to the tenant-wide branding address when the note has no warehouse linked', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(makeNote())
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(await screen.findByText(/Fallback tenant-wide address/)).toBeInTheDocument()
  })

  it('shows the physical document number and packing list invoice numbers', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(
      makeNote({ physical_document_number: '08280', packing_list_invoice_numbers: ['#53534', '#53535'] }),
    )
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(screen.getByText('08280')).toBeInTheDocument()
    expect(screen.getByText('#53534, #53535')).toBeInTheDocument()
  })

  it('shows amount paid, balance owed, and ON CREDIT status when on credit with no receipt yet', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(
      makeNote({
        is_on_credit: true,
        credit_granted_by_name: 'Mr Hassel',
        amount_paid_ngn: '100000.00',
        balance_ngn: '50000.00',
        total_ngn: '150000.00',
        debt_due_date: '2026-09-30',
      }),
    )
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(screen.getByText('100,000')).toBeInTheDocument()
    expect(screen.getByText('50,000')).toBeInTheDocument()
    expect(screen.getByText('ON CREDIT')).toBeInTheDocument()
    expect(screen.getByText('Mr Hassel')).toBeInTheDocument()
    expect(screen.getByText('2026-09-30')).toBeInTheDocument()
  })

  it('shows the receipt number instead of ON CREDIT once a payment is linked', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(
      makeNote({ is_on_credit: true, receipt_number: 'ACM-RCT-20260913-0001', amount_paid_ngn: '150000.00' }),
    )
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(screen.getByText('ACM-RCT-20260913-0001')).toBeInTheDocument()
    expect(screen.queryByText('ON CREDIT')).toBeNull()
  })

  it('shows the balance of cartons remaining on a partial release', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(
      makeNote({ is_partial_release: true, carton_count: 3, total_cartons_for_customer: 10, packages_balance: 7 }),
    )
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('renders all four named sign-off lines and the footer disclaimer', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(makeNote())
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(screen.getByText(/Customer's Rep/)).toBeInTheDocument()
    expect(screen.getByText(/Customer Service Officer/)).toBeInTheDocument()
    expect(screen.getByText(/Accounting Officer/)).toBeInTheDocument()
    expect(screen.getByText(/Warehouse Attendant/)).toBeInTheDocument()
    expect(screen.getByText(/must be confirmed by the customer before leaving/i)).toBeInTheDocument()
  })

  it('omits the payment block entirely when nothing was paid, nothing owed, and not on credit', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(makeNote({ amount_paid_ngn: '0', balance_ngn: '0', is_on_credit: false }))
    renderPage()

    await screen.findByText('ACM-RN-20260913-0001')
    expect(screen.queryByText('Amount paid (₦)')).toBeNull()
  })

  it('waits for the API call before asserting nothing renders prematurely', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(makeNote())
    renderPage()

    await waitFor(() => expect(releaseNotesApi.get).toHaveBeenCalledWith('note-001'))
  })
})
