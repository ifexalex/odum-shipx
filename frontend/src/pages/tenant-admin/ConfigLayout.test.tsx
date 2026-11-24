/**
 * ConfigLayout — the persistent /admin/config/* sub-nav rail. Regression: the
 * Webhooks screen used to render its own internal ConfigNav, which showed a
 * second navigation column once ConfigLayout landed (double rail).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { configApi } from '../../api/tenantManagement'
import { ConfigLayout } from './ConfigLayout'
import { WebhookConfig } from './WebhookConfig'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    configApi: { ...original.configApi, getConfig: vi.fn(), updateConfig: vi.fn() },
  }
})

function renderWebhooks() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/admin/config/webhooks']}>
        <Routes>
          <Route path="/admin/config/webhooks" element={<ConfigLayout><WebhookConfig /></ConfigLayout>} />
          <Route path="/admin/config/cbm-rate" element={<ConfigLayout><div>CBM rate page</div></ConfigLayout>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ConfigLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.getConfig).mockResolvedValue({
      webhook_config: { endpoint_url: 'https://erp.example.com/hook', enabled: true, events: [], secret: '****' },
      branding_config: null,
    })
  })

  it('renders exactly one navigation rail on the Webhooks screen (no leftover internal nav)', async () => {
    renderWebhooks()
    expect(await screen.findByText('Outbound webhook')).toBeInTheDocument()

    // Each section appears exactly once in the rail — a second rail would duplicate these. ("Webhooks" is also the
    // page's own title, in its PageHeader.)
    for (const label of ['Company', 'Dollar rate', 'CBM rate', 'Charge types', 'Webhooks']) {
      expect(screen.getAllByText(label, { selector: '[class*="subNavLabel"]' })).toHaveLength(1)
    }
    expect(screen.getByRole('heading', { level: 1, name: 'Webhooks' })).toBeInTheDocument()
    expect(screen.getByText('Webhooks', { selector: '[class*="subNavLabel"]' }).closest('[aria-current="page"]')).toBeTruthy()
  })

  it('rail navigation swaps only the content area', async () => {
    renderWebhooks()
    await screen.findByText('Outbound webhook')

    await userEvent.click(screen.getByText('CBM rate'))
    expect(await screen.findByText('CBM rate page')).toBeInTheDocument()
    // Rail persists after the route change
    expect(screen.getByText('Webhooks')).toBeInTheDocument()
    expect(screen.queryByText('Outbound webhook')).toBeNull()
  })
})
