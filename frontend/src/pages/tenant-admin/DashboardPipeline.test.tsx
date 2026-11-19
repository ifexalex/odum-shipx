import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { containersApi, type ContainerStats } from '../../api/tracking'
import { ContainerPipeline } from './DashboardPipeline'

vi.mock('../../api/tracking', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tracking')>()
  return { ...original, containersApi: { ...original.containersApi, list: vi.fn() } }
})

const STATS: ContainerStats = {
  total: 20, loading: 3, sealed: 2, in_transit: 5, arrived: 4, customs_clearance: 2,
  cleared: 1, at_warehouse: 2, fully_released: 1, cancelled: 0, cleared_30d: 0,
}

function container(id: string, number: string, status: string) {
  return {
    id, tenant_id: 't1', container_number: number, parcel_number: null,
    origin: 'Guangzhou', destination: 'Lagos', ship_date: null,
    estimated_arrival_date: '2026-08-14', actual_arrival_date: null, status,
    notes: null, created_by: 's1', created_at: '2026-07-01', updated_at: '2026-07-01',
    vessel_name: 'Ever Given', voyage_number: null, shipping_line: null, seal_number: null,
    container_type: null, capacity_cbm: null, recommended_cbm: null, created_by_name: null,
    packing_list_count: 4,
  }
}

function renderPipeline() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ContainerPipeline counts={STATS} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ContainerPipeline', () => {
  beforeEach(() => {
    vi.mocked(containersApi.list).mockReset().mockResolvedValue({
      data: [container('c1', 'MSCU1234567', 'in_transit')],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
  })

  it('shows every stage with its count — no horizontal-scroll kanban, nothing hidden', async () => {
    renderPipeline()
    // All eight stages + the "All active" lead tile are always rendered.
    for (const label of ['All active', 'Loading', 'Sealed', 'In transit', 'Arrived in Nigeria', 'Customs clearance', 'Cleared', 'At warehouse', 'Fully released']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // Counts come straight from the stats (no 6-card cap).
    expect(screen.getByText('5')).toBeInTheDocument() // in_transit
    expect(screen.getByText('20')).toBeInTheDocument() // all active total
  })

  it('defaults to the full active list', async () => {
    renderPipeline()
    await waitFor(() =>
      expect(containersApi.list).toHaveBeenCalledWith(
        expect.objectContaining({
          status: 'loading,sealed,in_transit,arrived,customs_clearance,cleared,at_warehouse,fully_released',
        }),
      ),
    )
    await waitFor(() => expect(screen.getByText('MSCU1234567')).toBeInTheDocument())
  })

  it('selecting a stage refetches the complete list filtered to that stage', async () => {
    vi.mocked(containersApi.list).mockImplementation((params) =>
      Promise.resolve({
        data: params?.status === 'at_warehouse' ? [container('c9', 'WHSE0001', 'at_warehouse')] : [container('c1', 'MSCU1234567', 'in_transit')],
        meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
      }) as never,
    )
    renderPipeline()
    await userEvent.click(screen.getByText('At warehouse'))
    await waitFor(() =>
      expect(containersApi.list).toHaveBeenCalledWith(expect.objectContaining({ status: 'at_warehouse' })),
    )
    await waitFor(() => expect(screen.getByText('WHSE0001')).toBeInTheDocument())
  })

  it('passes the search box text to the query as ?q= (debounced)', async () => {
    renderPipeline()
    await screen.findByText('MSCU1234567')
    await userEvent.type(screen.getByPlaceholderText(/Search container number/), 'ACME9057')
    await waitFor(() =>
      expect(containersApi.list).toHaveBeenCalledWith(expect.objectContaining({ q: 'ACME9057' })),
    )
  })

  it('applies an "Arriving" ETA filter via eta_after/eta_before', async () => {
    renderPipeline()
    await screen.findByText('MSCU1234567')
    await userEvent.click(screen.getByText('≤ 7 days'))
    await waitFor(() =>
      expect(containersApi.list).toHaveBeenCalledWith(
        expect.objectContaining({ eta_after: expect.any(String), eta_before: expect.any(String) }),
      ),
    )
    // "Overdue" uses only an upper bound (ETA already in the past).
    await userEvent.click(screen.getByText('Overdue'))
    await waitFor(() => {
      const lastCall = vi.mocked(containersApi.list).mock.calls.at(-1)![0]!
      expect(lastCall.eta_before).toEqual(expect.any(String))
      expect(lastCall.eta_after).toBeUndefined()
    })
  })

  it('renders the container row with route and packing-list count', async () => {
    renderPipeline()
    const num = await screen.findByText('MSCU1234567')
    const row = num.closest('tr')!
    expect(within(row).getByText('Guangzhou → Lagos')).toBeInTheDocument()
    expect(within(row).getByText('4')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'View' })).toBeInTheDocument()
  })
})
