/**
 * Platform onboarding queue — lists shipping-company leads, filters by status,
 * and Provision hands a lead to CreateTenantPage (pre-fill via router state).
 */
import type { JSX } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformApi, type OnboardingRequest } from '../../api/tenantManagement'
import { OnboardingRequests } from './OnboardingRequests'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    platformApi: {
      ...original.platformApi,
      listOnboardingRequests: vi.fn(),
      updateOnboardingRequest: vi.fn(),
    },
  }
})

function lead(overrides: Partial<OnboardingRequest>): OnboardingRequest {
  return {
    id: 'req-0001',
    company_name: 'Acme Freight',
    contact_name: 'Ada Obi',
    contact_email: 'ada@acme.com',
    contact_phone: null,
    origin_country: 'China',
    destination_country: 'Nigeria',
    monthly_volume: null,
    notes: null,
    status: 'new',
    rejection_reason: null,
    tenant_id: null,
    created_at: '2026-10-10T00:00:00Z',
    ...overrides,
  }
}

const LEADS = [
  lead({ id: 'req-new', company_name: 'Acme Freight', status: 'new' }),
  lead({ id: 'req-done', company_name: 'Eze Logistics', status: 'provisioned' }),
]

// Surfaces the router state CreateTenantPage would receive on Provision.
function CreateTenantProbe(): JSX.Element {
  const state = useLocation().state as { lead?: OnboardingRequest } | null
  return <div>Create tenant for {state?.lead?.company_name ?? 'nobody'}</div>
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/platform/onboarding-requests']}>
        <Routes>
          <Route path="/platform/onboarding-requests" element={<OnboardingRequests />} />
          <Route path="/platform/tenants/new" element={<CreateTenantProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('OnboardingRequests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(platformApi.listOnboardingRequests).mockResolvedValue(LEADS)
  })

  it('lists leads and offers actions only on open ones', async () => {
    renderPage()
    expect(await screen.findByText('Acme Freight')).toBeInTheDocument()
    expect(screen.getByText('Eze Logistics')).toBeInTheDocument()

    const newRow = screen.getByText('Acme Freight').closest('tr')!
    expect(within(newRow).getByRole('button', { name: /provision/i })).toBeInTheDocument()
    expect(within(newRow).getByRole('button', { name: /mark contacted/i })).toBeInTheDocument()

    // A provisioned lead is terminal — no row actions.
    const doneRow = screen.getByText('Eze Logistics').closest('tr')!
    expect(within(doneRow).queryByRole('button', { name: /provision/i })).toBeNull()
  })

  it('Provision carries the lead to CreateTenantPage via router state', async () => {
    renderPage()
    const newRow = (await screen.findByText('Acme Freight')).closest('tr')!
    await userEvent.click(within(newRow).getByRole('button', { name: /provision/i }))
    expect(await screen.findByText('Create tenant for Acme Freight')).toBeInTheDocument()
  })

  it('rejects a lead with a reason', async () => {
    vi.mocked(platformApi.updateOnboardingRequest).mockResolvedValue(lead({ status: 'rejected' }))
    renderPage()
    const newRow = (await screen.findByText('Acme Freight')).closest('tr')!
    await userEvent.click(within(newRow).getByRole('button', { name: /reject/i }))

    await userEvent.type(screen.getByLabelText('Reason', { exact: false, selector: 'input' }), 'Out of corridor')
    await userEvent.click(screen.getByRole('button', { name: /reject request/i }))

    expect(platformApi.updateOnboardingRequest).toHaveBeenCalledWith('req-new', 'rejected', 'Out of corridor')
  })
})
