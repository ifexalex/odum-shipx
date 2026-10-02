import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { manifestApi, type Manifest } from '../../api/manifest'
import { ManifestList } from './ManifestList'

vi.mock('../../api/manifest', () => ({
  manifestApi: { list: vi.fn(), stats: vi.fn() },
}))

function renderPage() {
  return render(
    <QueryClientProvider client={__qc()}><MemoryRouter>
      <ManifestList />
    </MemoryRouter></QueryClientProvider>,
  )
}

function manifestStub(overrides: Partial<Manifest> = {}): Manifest {
  return {
    id: 'mf1',
    tenant_id: 't1',
    container_id: 'c1',
    container_number: 'HLBU9384712',
    container_status: 'loading',
    total_customers: 8,
    total_cartons: 64,
    total_weight_kg: '412.000',
    total_cbm: '8.420000',
    verification_status: 'pending',
    verified_by: null,
    verified_at: null,
    notes: null,
    customers: [],
    created_at: '2026-07-28',
    updated_at: '2026-07-28',
    ...overrides,
  }
}

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('ManifestList', () => {
  beforeEach(() => {
    vi.mocked(manifestApi.list).mockReset()
    vi.mocked(manifestApi.list).mockResolvedValue({
      data: [manifestStub()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(manifestApi.stats).mockReset()
    vi.mocked(manifestApi.stats).mockResolvedValue({
      pending: 3, verified: 5, discrepancies_found: 1, resolved: 2, overdue: 1,
    })
  })

  it('loads and renders manifests with formatted CBM', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('HLBU9384712')).toBeInTheDocument())
    expect(screen.getByText('8.420')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('Pending')).toBeInTheDocument()
  })

  it('refetches with the verification_status filter when a chip is clicked', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('HLBU9384712')).toBeInTheDocument())

    // 'Verified' now also appears as a stat-card label (P2-4) — target the chip button.
    const chip = screen.getAllByText('Verified').find((el) => el.closest('button'))
    await userEvent.click(chip!)
    await waitFor(() =>
      expect(manifestApi.list).toHaveBeenLastCalledWith({ verification_status: 'verified' }),
    )
  })

  it('shows an empty state when there are no manifests', async () => {
    vi.mocked(manifestApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('No manifests yet.')).toBeInTheDocument())
  })
  it('flags a manifest as overdue when pending and the container has arrived in Nigeria (B11)', async () => {
    vi.mocked(manifestApi.list).mockResolvedValue({
      data: [manifestStub({ verification_status: 'pending', container_status: 'customs_clearance' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('HLBU9384712')).toBeInTheDocument())
    // Row Overdue badge + the summary banner
    expect(within(screen.getByRole('table')).getByText('Overdue')).toBeInTheDocument()
    expect(screen.getByText(/1 manifest overdue for verification/i)).toBeInTheDocument()
  })

  it('does not flag a pending manifest whose container is still in transit', async () => {
    vi.mocked(manifestApi.list).mockResolvedValue({
      data: [manifestStub({ verification_status: 'pending', container_status: 'in_transit' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('HLBU9384712')).toBeInTheDocument())
    expect(screen.queryByText('Overdue')).toBeNull()
    expect(screen.queryByText(/overdue for verification/i)).toBeNull()
  })

  it('does not flag an already-verified manifest even if the container has arrived', async () => {
    vi.mocked(manifestApi.list).mockResolvedValue({
      data: [manifestStub({ verification_status: 'verified', container_status: 'at_warehouse' })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('HLBU9384712')).toBeInTheDocument())
    expect(screen.queryByText('Overdue')).toBeNull()
  })
})
