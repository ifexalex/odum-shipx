/**
 * 15.4A / audit gap B9 — plan-usage panel: per-dimension bars with the
 * 80%-warning and at-limit treatments, unlimited counters as a meta line.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { quotaApi } from '../api/tenantManagement'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { PlanUsagePanel } from './PlanUsagePanel'

vi.mock('../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/tenantManagement')>()
  return { ...original, quotaApi: { getMyQuota: vi.fn() } }
})

const QUOTA = {
  tenant_id: 't1',
  period: '2026-07',
  subscription_tier: 'starter',
  limits: {
    users: { used: 10, max: 10 },                 // at limit
    containers_per_month: { used: 17, max: 20 },  // 85% — warning
    storage_gb: { used: 2, max: 5 },              // 40% — quiet
  },
  api_calls: 4200,
  notifications: { sms_sent: 1840, whatsapp_sent: 220, emails_sent: 96 },
}

function renderPanel() {
  const session: Session = {
    tenantId: 't1', userId: 'u1', name: 'Amara', role: 'tenant_admin', roles: ['tenant_admin'],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null,
    readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
  const ctx: SessionContextValue = {
    session, status: 'authenticated',
    login: vi.fn(), logout: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider value={ctx}>
        <MemoryRouter>
          <PlanUsagePanel />
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

describe('PlanUsagePanel (B9)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(quotaApi.getMyQuota).mockResolvedValue(QUOTA as never)
  })

  it('renders tier, per-dimension bars, and threshold badges', async () => {
    renderPanel()

    expect(await screen.findByText('Plan usage · Starter')).toBeInTheDocument()
    expect(screen.getByText('10 / 10')).toBeInTheDocument()
    expect(screen.getByText('At limit')).toBeInTheDocument()   // users
    expect(screen.getByText('85%')).toBeInTheDocument()        // containers — amber badge
    expect(screen.getByText('40%')).toBeInTheDocument()        // storage — quiet
    expect(screen.getByText('2 / 5 GB')).toBeInTheDocument()
  })

  it('reports unlimited counters as plain text, never as bars', async () => {
    renderPanel()
    expect(
      await screen.findByText(/4,200 API calls · 1,840 SMS · 220 WhatsApp · 96 email/),
    ).toBeInTheDocument()
  })
})
