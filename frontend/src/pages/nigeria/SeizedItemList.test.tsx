import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { seizedItemsApi } from '../../api/claims'
import { SeizedItemList } from './SeizedItemList'

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
  id: 's1',
  container_id: 'cont1',
  customer_id: 'cust1',
  carton_tags: ['C010'],
  reason: 'Undeclared electronics seized by customs',
  status: 'seized' as const,
  created_at: '2026-06-10T09:00:00Z',
}

beforeEach(() => { vi.mocked(seizedItemsApi.list).mockReset() })

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('SeizedItemList', () => {
  it('renders seized items', async () => {
    vi.mocked(seizedItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><SeizedItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('Undeclared electronics seized by customs')).toBeInTheDocument())
    // 'Seized' appears as chip and badge — scope to table
    expect(within(screen.getByRole('table')).getByText('Seized')).toBeInTheDocument()
  })

  it('shows Update button for nigeria on active seized items', async () => {
    vi.mocked(seizedItemsApi.list).mockResolvedValue({ data: [ITEM_STUB], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><SeizedItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument())
  })

  it('hides Update for terminal status (recovered)', async () => {
    vi.mocked(seizedItemsApi.list).mockResolvedValue({ data: [{ ...ITEM_STUB, status: 'recovered' }], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><SeizedItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText('Recovered')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Update' })).not.toBeInTheDocument()
  })

  it('shows empty state', async () => {
    vi.mocked(seizedItemsApi.list).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    render(<QueryClientProvider client={__qc()}><MemoryRouter><SessionContext.Provider value={makeCtx()}><SeizedItemList /></SessionContext.Provider></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(screen.getByText(/No seized items/)).toBeInTheDocument())
  })
})
