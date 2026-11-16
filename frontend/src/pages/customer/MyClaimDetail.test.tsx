import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { claimsApi, type Claim } from '../../api/claims'
import { ApiError } from '../../api/client'
import { MyClaimDetail } from './MyClaimDetail'

vi.mock('../../api/claims', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/claims')>()),
  claimsApi: { get: vi.fn(), list: vi.fn() },
}))

const CLAIM: Claim = {
  id: 'cl1',
  reference: 'DC-20261110-001',
  status: 'under_inspection',
  container_id: 'k1',
  container_number: 'MSCU1234567',
  customer_id: 'c1',
  customer_name: 'Ngozi Adeyemi',
  description: 'Two cartons arrived soaked.',
  inspection_method: 'customer_evidence',
  cartons_affected: ['T-0001', 'T-0002'],
  upload_urls: null,
  created_at: '2026-11-10T10:00:00Z',
  evidence: [
    { id: 'e1', file_name: 'soaked.jpg', file_type: 'image/jpeg', file_size_bytes: 204_800, uploaded_at: '2026-11-10T10:05:00Z', download_url: 'https://files.example/soaked.jpg?sig=1' },
  ],
  resolution: null,
  refund: null,
}

function renderPage(id = 'cl1') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/my-claims/${id}`]}>
        <Routes>
          <Route path="/my-claims/:id" element={<MyClaimDetail />} />
          <Route path="/my-claims" element={<div>Claims list</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(claimsApi.get).mockReset()
})

describe('MyClaimDetail (UX-07)', () => {
  it('shows what the customer filed, in their own terms', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue(CLAIM)
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Claim DC-20261110-001' })).toBeInTheDocument()
    expect(screen.getByText('Filed 10 Nov 2026')).toBeInTheDocument()
    expect(screen.getByText('MSCU1234567')).toBeInTheDocument()
    expect(screen.getByText('T-0001, T-0002')).toBeInTheDocument()
    expect(screen.getByText('Two cartons arrived soaked.')).toBeInTheDocument()
    expect(screen.getByText('From the photos and videos you provided')).toBeInTheDocument()
  })

  it('marks where the claim has got to', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue(CLAIM)
    renderPage()
    const steps = within(await screen.findByRole('list', { name: 'Claim progress' }))
    expect(steps.getByText('✓ Filed')).toBeInTheDocument()
    expect(steps.getByText('Under inspection')).toHaveAttribute('aria-current', 'step')
    expect(steps.getByText('Resolved')).not.toHaveAttribute('aria-current')
  })

  it('lists the evidence with a link that opens safely in a new tab', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue(CLAIM)
    renderPage()
    const link = await screen.findByRole('link', { name: 'Open soaked.jpg' })
    expect(link).toHaveAttribute('href', 'https://files.example/soaked.jpg?sig=1')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
    expect(screen.getByText(/200 KB/)).toBeInTheDocument()
  })

  it('says so when a file has no link, and when there are no files', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue({ ...CLAIM, evidence: [{ ...CLAIM.evidence![0]!, download_url: null }] })
    const { unmount } = renderPage()
    expect(await screen.findByText('Unavailable')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Open soaked/ })).toBeNull()
    unmount()

    vi.mocked(claimsApi.get).mockResolvedValue({ ...CLAIM, evidence: [] })
    renderPage()
    expect(await screen.findByText('No files were attached to this claim.')).toBeInTheDocument()
  })

  it('says there is no decision yet, and what is being waited for, while it is open', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue({ ...CLAIM, status: 'pending_resolution' })
    renderPage()
    expect(await screen.findByText('No decision yet')).toBeInTheDocument()
    expect(screen.getByText(/deciding the outcome/)).toBeInTheDocument()
  })

  it('shows the outcome and the refund once decided', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue({
      ...CLAIM,
      status: 'resolved',
      resolution: { resolution_type: 'refund', amount_ngn: '30000.00', discount_percentage: null, resolved_at: '2026-11-12T09:00:00Z' },
      refund: { id: 'r1', status: 'approved', amount_ngn: '25000.00' },
    })
    renderPage()
    const outcome = within((await screen.findByRole('heading', { name: 'Outcome' })).closest('div')!)
    expect(outcome.getByText('Refund')).toBeInTheDocument() // the decision; the status row is labelled 'Refund status'
    expect(outcome.getByText('₦30,000')).toBeInTheDocument()
    expect(outcome.getByText('12 Nov 2026')).toBeInTheDocument()
    expect(outcome.getByText('Approved: the payout is being arranged')).toBeInTheDocument()
    expect(outcome.getByText('₦25,000')).toBeInTheDocument()
    expect(screen.queryByText('No decision yet')).toBeNull()
  })

  it('describes a discount by its percentage and a closed-without-payout claim plainly', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue({
      ...CLAIM,
      status: 'resolved',
      resolution: { resolution_type: 'discount', amount_ngn: null, discount_percentage: '15.00', resolved_at: '2026-11-12T09:00:00Z' },
    })
    const { unmount } = renderPage()
    expect(await screen.findByText('15% discount')).toBeInTheDocument()
    unmount()

    vi.mocked(claimsApi.get).mockResolvedValue({
      ...CLAIM,
      status: 'closed',
      resolution: { resolution_type: 'no_action', amount_ngn: '0.00', discount_percentage: null, resolved_at: '2026-11-12T09:00:00Z' },
    })
    renderPage()
    expect(await screen.findByText('Closed without a payout')).toBeInTheDocument()
    expect(screen.queryByText('Amount')).toBeNull()
  })

  it('answers a claim that is not theirs, or does not exist, with "Claim not found."', async () => {
    vi.mocked(claimsApi.get).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'Not Found', status: 404, detail: 'x', error_code: 'RESOURCE_NOT_FOUND' }, null),
    )
    renderPage('someone-elses')
    expect(await screen.findByText('Claim not found.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Back to my claims/ }))
    expect(screen.getByText('Claims list')).toBeInTheDocument()
  })

  it('says it could not load, rather than "not found", for any other failure', async () => {
    vi.mocked(claimsApi.get).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'Server Error', status: 500, detail: 'x', error_code: 'INTERNAL' }, null),
    )
    renderPage()
    expect(await screen.findByText('Could not load this claim. Please try again.')).toBeInTheDocument()
  })

  it('goes back to the list', async () => {
    vi.mocked(claimsApi.get).mockResolvedValue(CLAIM)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /Back to my claims/ }))
    expect(screen.getByText('Claims list')).toBeInTheDocument()
  })
})
