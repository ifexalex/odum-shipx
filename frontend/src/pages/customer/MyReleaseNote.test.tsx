import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { releaseNotesApi, type ReleaseNote } from '../../api/releaseNotes'
import { MyReleaseNote } from './MyReleaseNote'
import { ReleaseNoteCard } from './ReleaseNoteCard'

vi.mock('../../api/releaseNotes', () => ({
  releaseNotesApi: { get: vi.fn(), list: vi.fn(), pdf: vi.fn() },
}))

const NOTE = {
  id: 'n1', reference_number: 'ACME-RN-0001', customer_name: 'Ngozi', container_number: 'MSKU1234567',
  carton_count: 4, total_cartons_for_customer: 10, is_partial_release: true, carton_tags: ['T1', 'T2'],
  packages_released: null, package_unit: null, packages_balance: null, payment_status: 'paid', status: 'active',
  authorized_at: '2026-11-01T10:00:00Z', warehouse_address: '3 Capital Plaza, Lagos', warehouse_name: 'Lagos Island',
  warehouse_phone: '0706 617 1191', is_on_credit: false, credit_granted_by_name: null, receipt_number: null,
  physical_document_number: null, packing_list_invoice_numbers: [], amount_paid_ngn: '100', balance_ngn: '0',
  total_ngn: '100', debt_due_date: null, valid_until: '2026-12-01',
} as ReleaseNote

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderPage(path = '/my-release-notes/n1') {
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/my-release-notes/:id" element={<MyReleaseNote />} />
          <Route path="/my-billing" element={<div>Billing list</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MyReleaseNote', () => {
  beforeEach(() => vi.clearAllMocks())

  it('tells the customer a pickup code is needed, and to share it only with the collector (UX-09)', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue({ ...NOTE, pickup_code_required: true })
    renderPage()
    expect(await screen.findByText('A pickup code is needed')).toBeInTheDocument()
    expect(screen.getByText(/share it only with them/)).toBeInTheDocument()
  })

  it('tells the customer when wrong codes have locked the note', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue({ ...NOTE, pickup_code_required: true, pickup_code_locked: true })
    renderPage()
    expect(await screen.findByText('Pickup code locked')).toBeInTheDocument()
    expect(screen.queryByText('A pickup code is needed')).toBeNull()
  })

  it('says nothing about a code on a note that has none', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(NOTE)
    renderPage()
    await screen.findByText('ACME-RN-0001')
    expect(screen.queryByText(/pickup code/i)).toBeNull()
  })

  it('shows what a customer needs at the warehouse', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(NOTE)
    renderPage()

    expect(await screen.findByText('ACME-RN-0001')).toBeInTheDocument()
    expect(screen.getByText('Ready for collection')).toBeInTheDocument()
    expect(screen.getByText('4 of 10 cartons')).toBeInTheDocument()
    expect(screen.getByText('MSKU1234567')).toBeInTheDocument()
    expect(screen.getByText('Lagos Island')).toBeInTheDocument()
    expect(screen.getByText('3 Capital Plaza, Lagos')).toBeInTheDocument()
    expect(screen.getByText('1 Dec 2026')).toBeInTheDocument()
    expect(screen.getByText(/Partial/)).toBeInTheDocument()
  })

  it('downloads the PDF', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(NOTE)
    vi.mocked(releaseNotesApi.pdf).mockResolvedValue(undefined)
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /Download PDF/ }))
    await waitFor(() => expect(releaseNotesApi.pdf).toHaveBeenCalledWith('n1'))
  })

  it('says so when the PDF cannot be downloaded', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue(NOTE)
    vi.mocked(releaseNotesApi.pdf).mockRejectedValue(new Error('network'))
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /Download PDF/ }))
    expect(await screen.findByText(/Could not download the PDF/)).toBeInTheDocument()
  })

  it("shows 'not found' for a note that is not theirs (the API answers 404)", async () => {
    vi.mocked(releaseNotesApi.get).mockRejectedValue(
      new ApiError({ type: 'x', title: 'x', status: 404, detail: 'not found', error_code: 'RESOURCE_NOT_FOUND' }, null),
    )
    renderPage('/my-release-notes/someone-elses')

    expect(await screen.findByText('Release note not found.')).toBeInTheDocument()
    expect(screen.queryByText('Download PDF')).toBeNull()
  })

  it('warns when released on credit with a balance', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue({ ...NOTE, is_on_credit: true, balance_ngn: '25000', debt_due_date: '2026-12-15' })
    renderPage()
    expect(await screen.findByText('Released on credit')).toBeInTheDocument()
    expect(screen.getByText(/25,000/)).toBeInTheDocument()
  })

  it('flags an expired note', async () => {
    vi.mocked(releaseNotesApi.get).mockResolvedValue({ ...NOTE, status: 'expired' })
    renderPage()
    expect(await screen.findByText('This release note has expired')).toBeInTheDocument()
    expect(screen.queryByText('Ready for collection')).toBeNull()
  })
})

describe('ReleaseNoteCard', () => {
  beforeEach(() => vi.clearAllMocks())

  function renderCard(containerId: string | undefined) {
    return render(
      <QueryClientProvider client={client()}>
        <MemoryRouter initialEntries={['/x']}>
          <Routes>
            <Route path="/x" element={<ReleaseNoteCard containerId={containerId} />} />
            <Route path="/my-release-notes/:id" element={<div>The note page</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('renders nothing before a note exists', async () => {
    vi.mocked(releaseNotesApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    const { container } = renderCard('c1')
    await waitFor(() => expect(releaseNotesApi.list).toHaveBeenCalledWith({ container_id: 'c1' }))
    expect(container).toBeEmptyDOMElement()
  })

  it('lists the notes for the container and opens one', async () => {
    vi.mocked(releaseNotesApi.list).mockResolvedValue({ data: [NOTE], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    renderCard('c1')
    expect(await screen.findByText('Your release note')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(await screen.findByText('The note page')).toBeInTheDocument()
  })

  it('does not ask for notes without a container', () => {
    renderCard(undefined)
    expect(releaseNotesApi.list).not.toHaveBeenCalled()
  })

  it('renders nothing when the lookup fails: the page it sits on still works', async () => {
    vi.mocked(releaseNotesApi.list).mockRejectedValue(new Error('down'))
    const { container } = renderCard('c1')
    await waitFor(() => expect(releaseNotesApi.list).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
