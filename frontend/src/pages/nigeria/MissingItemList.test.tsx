import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { missingItemsApi } from '../../api/claims'
import { MissingItemList } from './MissingItemList'

vi.mock('../../api/claims', () => ({
  claimsApi: { list: vi.fn(), get: vi.fn(), file: vi.fn(), startInspection: vi.fn(), resolve: vi.fn() },
  missingItemsApi: { list: vi.fn(), get: vi.fn(), update: vi.fn() },
  seizedItemsApi: { list: vi.fn(), get: vi.fn(), update: vi.fn() },
  presignedUploadApi: { getUrl: vi.fn() },
}))

function makeCtx(role = 'nigeria_office_staff'): SessionContextValue {
  const session: Session = {
    tenantId: 't1', userId: 'u1', name: null, role: role as Session['role'], roles: [role as Session['role']],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null,
    readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
  return { session, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }
}

const ITEM_STUB = {
  id: 'm1',
  manifest_id: 'mf1',
  customer_id: 'cust1',
  carton_tags: ['C005', 'C006'],
  description: 'Electronic components',
  status: 'reported' as const,
  created_at: '2026-06-01T10:00:00Z',
}

beforeEach(() => { vi.mocked(missingItemsApi.list).mockReset() })

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('MissingItemList', () => {
  it('renders missing items', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('Electronic components')).toBeInTheDocument())
    expect(screen.getByText('C005, C006')).toBeInTheDocument()
  })

  it('shows Update button for nigeria on non-resolved items', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument())
  })

  it('hides Update button for tenant_admin', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx('tenant_admin')}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('Electronic components')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Update' })).not.toBeInTheDocument()
  })

  it('shows empty state', async () => {
    vi.mocked(missingItemsApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><MissingItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText(/No missing items/)).toBeInTheDocument())
  })
})
