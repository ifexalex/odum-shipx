import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { containersApi, type Container } from '../../api/tracking'
import { CreateContainer } from './CreateContainer'

vi.mock('../../api/tracking', () => ({
  containersApi: { create: vi.fn() },
}))
vi.mock('../../api/tenantManagement', () => ({
  containerCapacitiesApi: { list: vi.fn().mockResolvedValue([]) },
  configApi: { getConfig: vi.fn().mockResolvedValue({ webhook_config: null, default_transit_days: 45 }) },
}))

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CreateContainer />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CreateContainer', () => {
  beforeEach(() => {
    vi.mocked(containersApi.create).mockReset()
  })

  it('disables submit until a container number is entered and omits ETA on creation (ENG-1)', () => {
    renderPage()
    expect(screen.getByRole('button', { name: 'Create container' })).toBeDisabled()
    expect(screen.queryByLabelText(/estimated arrival date/i)).toBeNull()
  })

  it('submits with an idempotency key and the entered fields', async () => {
    const created: Container = {
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
    vi.mocked(containersApi.create).mockResolvedValue(created)
    renderPage()
    await userEvent.type(screen.getByLabelText('Container number', { exact: false, selector: 'input' }), 'mscu1234567')
    await userEvent.click(screen.getByRole('button', { name: 'Create container' }))
    await waitFor(() => expect(containersApi.create).toHaveBeenCalledTimes(1))
    const [body, idemKey] = vi.mocked(containersApi.create).mock.calls[0]!
    expect(body.container_number).toBe('MSCU1234567')
    expect(body.estimated_arrival_date).toBeUndefined()
    expect(typeof idemKey).toBe('string')
    expect(idemKey.length).toBeGreaterThan(0)
  })

  it('shows an error banner when the API call fails', async () => {
    vi.mocked(containersApi.create).mockRejectedValue(new Error('boom'))
    renderPage()
    await userEvent.type(screen.getByLabelText('Container number', { exact: false, selector: 'input' }), 'MSCU1234567')
    await userEvent.click(screen.getByRole('button', { name: 'Create container' }))
    await waitFor(() => expect(screen.getByText(/couldn't create container/i)).toBeInTheDocument())
  })
})

describe('CreateContainer sent from another form (FD-25)', () => {
  it('goes back to the form that needed the container', async () => {
    vi.mocked(containersApi.create).mockResolvedValue({ id: 'c9', container_number: 'MSCU7654321' } as Container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/containers/new?return=%2Fpacking-lists%2Fnew']}>
          <Routes>
            <Route path="/containers/new" element={<CreateContainer />} />
            <Route path="/packing-lists/new" element={<p>Packing list wizard</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.type(screen.getByLabelText('Container number', { exact: false, selector: 'input' }), 'MSCU7654321')
    await userEvent.click(screen.getByRole('button', { name: 'Create container' }))
    expect(await screen.findByText('Packing list wizard')).toBeInTheDocument()
  })

  it('ignores a return path that leaves the app', async () => {
    vi.mocked(containersApi.create).mockResolvedValue({ id: 'c9', container_number: 'MSCU7654321' } as Container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/containers/new?return=%2F%2Fevil.example']}>
          <Routes>
            <Route path="/containers/new" element={<CreateContainer />} />
            <Route path="/containers/:id" element={<p>Container page</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.type(screen.getByLabelText('Container number', { exact: false, selector: 'input' }), 'MSCU7654321')
    await userEvent.click(screen.getByRole('button', { name: 'Create container' }))
    expect(await screen.findByText('Container page')).toBeInTheDocument()
  })
})
