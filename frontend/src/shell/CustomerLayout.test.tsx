import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { customerNotificationsApi } from '../api/customerNotifications'
import { CustomerLayout } from './CustomerLayout'

vi.mock('../api/customerNotifications', () => ({
  customerNotificationsApi: {
    list: vi.fn(),
    unreadCount: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
    getBanner: vi.fn().mockResolvedValue(null),
  },
}))

function renderLayout(value: SessionContextValue, children = <div>Shipments content</div>, path = '/my-shipments') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>
          <CustomerLayout>{children}</CustomerLayout>
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

function makeSession(): Session {
  return {
    tenantId: 't1',
    userId: 'u1',
    role: 'customer',
    roles: ['customer'],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  name: null,
  }
}

function makeContextValue(overrides: Partial<SessionContextValue>): SessionContextValue {
  return {
    session: null,
    status: 'unauthenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(customerNotificationsApi.unreadCount).mockReset()
  vi.mocked(customerNotificationsApi.list).mockReset()
  vi.mocked(customerNotificationsApi.getBanner).mockReset().mockResolvedValue(null)
})

describe('CustomerLayout', () => {
  it('renders the customer top nav and the children content', () => {
    vi.mocked(customerNotificationsApi.unreadCount).mockResolvedValue({ unread_count: 0 })
    renderLayout(makeContextValue({ session: makeSession(), status: 'authenticated' }))
    expect(screen.getByText('Shipments content')).toBeInTheDocument()
    expect(screen.getByText('My Shipments')).toBeInTheDocument()
    expect(screen.getByText('Account')).toBeInTheDocument()
  })

  it('renders nothing when there is no session', () => {
    const { container } = renderLayout(makeContextValue({}))
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the customer notification unread count on the bell', async () => {
    vi.mocked(customerNotificationsApi.unreadCount).mockResolvedValue({ unread_count: 2 })
    renderLayout(makeContextValue({ session: makeSession(), status: 'authenticated' }))
    expect(await screen.findByText('2')).toBeInTheDocument()
  })

  it('opens the notification panel when the bell is clicked', async () => {
    vi.mocked(customerNotificationsApi.unreadCount).mockResolvedValue({ unread_count: 1 })
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderLayout(makeContextValue({ session: makeSession(), status: 'authenticated' }))
    fireEvent.click(screen.getByRole('button', { name: /notifications/i }))
    expect(await screen.findByRole('dialog', { name: /notifications/i })).toBeInTheDocument()
  })

  it('shows the active announcement as a page banner', async () => {
    vi.mocked(customerNotificationsApi.unreadCount).mockResolvedValue({ unread_count: 0 })
    vi.mocked(customerNotificationsApi.getBanner).mockResolvedValue({
      id: 'ann1',
      tenant_id: 't1',
      target_role: 'customer',
      target_user_id: null,
      event_type: 'announcement',
      entity_type: 'announcement',
      entity_id: null,
      title: 'Customs delay this week',
      body: null,
      is_read: false,
      created_at: new Date().toISOString(),
    })
    renderLayout(makeContextValue({ session: makeSession(), status: 'authenticated' }))
    expect(await screen.findByText('Customs delay this week')).toBeInTheDocument()
  })

  it('shows no banner when nothing is active', async () => {
    vi.mocked(customerNotificationsApi.unreadCount).mockResolvedValue({ unread_count: 0 })
    renderLayout(makeContextValue({ session: makeSession(), status: 'authenticated' }))
    await screen.findByText('Shipments content')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('offers the customer a search box scoped to their own records', () => {
    renderLayout(makeContextValue({ session: makeSession(), status: 'authenticated' }))
    expect(screen.getByRole('combobox', { name: 'Search my shipments, invoices…' })).toBeInTheDocument()
  })
})
