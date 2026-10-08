import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { announcementsApi } from '../../api/announcements'
import { AnnouncementsPage } from './AnnouncementsPage'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'

vi.mock('../../api/announcements', () => ({
  announcementsApi: {
    send: vi.fn(),
    listPending: vi.fn(),
    listMine: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
    updateRequest: vi.fn(),
    deleteRequest: vi.fn(),
    listHistory: vi.fn(),
    activate: vi.fn(),
    deactivate: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}))

function makeSession(role: Session['role']): Session {
  return {
    tenantId: 't1',
    userId: 'u1',
    name: null,
    role,
    roles: [role],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
}

function makeContextValue(session: Session | null): SessionContextValue {
  return {
    session,
    status: session ? 'authenticated' : 'unauthenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(),
    setActiveRole: vi.fn(),
  }
}

function renderPage(session: Session | null) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeContextValue(session)}>
        <TopBarTestWrapper><AnnouncementsPage /></TopBarTestWrapper>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}

function makeRequest(overrides = {}) {
  return {
    id: 'req1',
    tenant_id: 't1',
    title: 'Customs delay',
    body: 'Expect 2-day delays.',
    audience: 'all_customers' as const,
    status: 'pending' as const,
    requested_by: 'u1',
    reviewed_by: null,
    reviewed_at: null,
    rejection_reason: null,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

function makeHistoryEntry(overrides = {}) {
  return {
    announcement_group_id: 'g1',
    title: 'Office closed',
    body: null,
    audience: 'all_staff' as const,
    banner_active: false,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(announcementsApi.send).mockReset()
  vi.mocked(announcementsApi.listPending).mockReset().mockResolvedValue({
    data: [],
    meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
  })
  vi.mocked(announcementsApi.listMine).mockReset().mockResolvedValue([])
  vi.mocked(announcementsApi.approve).mockReset()
  vi.mocked(announcementsApi.reject).mockReset()
  vi.mocked(announcementsApi.updateRequest).mockReset()
  vi.mocked(announcementsApi.deleteRequest).mockReset()
  vi.mocked(announcementsApi.listHistory).mockReset().mockResolvedValue([])
  vi.mocked(announcementsApi.activate).mockReset()
  vi.mocked(announcementsApi.deactivate).mockReset()
  vi.mocked(announcementsApi.update).mockReset()
  vi.mocked(announcementsApi.remove).mockReset()
})

describe('AnnouncementsPage — tenant_admin', () => {
  it('shows both management sections and empty states', async () => {
    renderPage(makeSession('tenant_admin'))

    expect(await screen.findByText(/no customer announcements awaiting approval/i)).toBeInTheDocument()
    expect(screen.getByText(/no announcements sent yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/my announcements/i)).toBeNull()
  })

  it('approves a pending request', async () => {
    vi.mocked(announcementsApi.listPending).mockResolvedValue({
      data: [makeRequest()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(announcementsApi.approve).mockResolvedValue({
      status: 'approved',
      audience: 'all_customers',
      notifications_created: 1,
    })
    renderPage(makeSession('tenant_admin'))

    await screen.findByText('Customs delay')
    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))

    await waitFor(() => expect(announcementsApi.approve).toHaveBeenCalledWith('req1'))
  })

  it('rejects a pending request with a reason', async () => {
    vi.mocked(announcementsApi.listPending).mockResolvedValue({
      data: [makeRequest()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(announcementsApi.reject).mockResolvedValue({ status: 'rejected' })
    renderPage(makeSession('tenant_admin'))

    await screen.findByText('Customs delay')
    await userEvent.click(screen.getByRole('button', { name: /^reject$/i }))
    await userEvent.type(screen.getByPlaceholderText(/why is this being rejected/i), 'Not accurate')
    await userEvent.click(screen.getByRole('button', { name: /confirm reject/i }))

    await waitFor(() => expect(announcementsApi.reject).toHaveBeenCalledWith('req1', 'Not accurate'))
  })

  it('shows Publish for a draft announcement and Unpublish for a published one', async () => {
    vi.mocked(announcementsApi.listHistory).mockResolvedValue([
      makeHistoryEntry({ announcement_group_id: 'draft1', title: 'Draft one', banner_active: false }),
      makeHistoryEntry({ announcement_group_id: 'live1', title: 'Live one', banner_active: true }),
    ])
    renderPage(makeSession('tenant_admin'))

    await screen.findByText('Draft one')
    expect(screen.getByText('Draft')).toBeInTheDocument()
    expect(screen.getByText('Published')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^publish$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^unpublish$/i })).toBeInTheDocument()
  })

  it('clicking Publish calls activate; clicking Unpublish calls deactivate', async () => {
    vi.mocked(announcementsApi.listHistory).mockResolvedValue([
      makeHistoryEntry({ announcement_group_id: 'draft1', title: 'Draft one', banner_active: false }),
    ])
    vi.mocked(announcementsApi.activate).mockResolvedValue({ announcement_group_id: 'draft1', banner_active: true })
    renderPage(makeSession('tenant_admin'))

    await screen.findByText('Draft one')
    await userEvent.click(screen.getByRole('button', { name: /^publish$/i }))

    await waitFor(() => expect(announcementsApi.activate).toHaveBeenCalledWith('draft1'))
  })

  it('edits a sent announcement', async () => {
    vi.mocked(announcementsApi.listHistory).mockResolvedValue([makeHistoryEntry()])
    vi.mocked(announcementsApi.update).mockResolvedValue({
      announcement_group_id: 'g1',
      title: 'Office closed (updated)',
      body: null,
    })
    renderPage(makeSession('tenant_admin'))

    await screen.findByText('Office closed')
    await userEvent.click(screen.getByRole('button', { name: /^edit$/i }))

    const titleInput = screen.getByDisplayValue('Office closed')
    await userEvent.clear(titleInput)
    await userEvent.type(titleInput, 'Office closed (updated)')
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() =>
      expect(announcementsApi.update).toHaveBeenCalledWith('g1', {
        title: 'Office closed (updated)',
        body: undefined,
      }),
    )
  })

  it('deletes a sent announcement after confirming', async () => {
    vi.mocked(announcementsApi.listHistory).mockResolvedValue([makeHistoryEntry()])
    vi.mocked(announcementsApi.remove).mockResolvedValue({ deleted: true })
    renderPage(makeSession('tenant_admin'))

    await screen.findByText('Office closed')
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => expect(announcementsApi.remove).toHaveBeenCalledWith('g1'))
  })

  it('opens the compose modal from "New announcement"', async () => {
    renderPage(makeSession('tenant_admin'))

    await userEvent.click(screen.getByRole('button', { name: /new announcement/i }))
    expect(await screen.findByRole('dialog', { name: /new announcement/i })).toBeInTheDocument()
  })
})

describe('AnnouncementsPage — nigeria_office_staff', () => {
  it('shows "My announcements" instead of the admin sections', async () => {
    renderPage(makeSession('nigeria_office_staff'))

    expect(await screen.findByText(/haven't submitted any announcements/i)).toBeInTheDocument()
    expect(screen.queryByText(/pending approval/i)).toBeNull()
    expect(screen.queryByText(/all announcements/i)).toBeNull()
  })

  it('shows the status of an own submission', async () => {
    vi.mocked(announcementsApi.listMine).mockResolvedValue([
      makeRequest({ status: 'approved', title: 'Approved notice' }),
    ])
    renderPage(makeSession('nigeria_office_staff'))

    await screen.findByText('Approved notice')
    expect(screen.getByText('Approved')).toBeInTheDocument()
  })

  it('shows the rejection reason for a rejected submission', async () => {
    vi.mocked(announcementsApi.listMine).mockResolvedValue([
      makeRequest({ status: 'rejected', title: 'Rejected notice', rejection_reason: 'Not accurate' }),
    ])
    renderPage(makeSession('nigeria_office_staff'))

    await screen.findByText('Rejected notice')
    expect(screen.getByText(/not accurate/i)).toBeInTheDocument()
  })

  it('allows editing and withdrawing a still-pending submission', async () => {
    vi.mocked(announcementsApi.listMine).mockResolvedValue([makeRequest()])
    renderPage(makeSession('nigeria_office_staff'))

    await screen.findByText('Customs delay')
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /withdraw/i })).toBeInTheDocument()
  })

  it('hides edit/withdraw controls for an already-reviewed submission', async () => {
    vi.mocked(announcementsApi.listMine).mockResolvedValue([makeRequest({ status: 'approved' })])
    renderPage(makeSession('nigeria_office_staff'))

    await screen.findByText('Customs delay')
    expect(screen.queryByRole('button', { name: /^edit$/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /withdraw/i })).toBeNull()
  })

  it('withdrawing calls deleteRequest', async () => {
    vi.mocked(announcementsApi.listMine).mockResolvedValue([makeRequest()])
    vi.mocked(announcementsApi.deleteRequest).mockResolvedValue({ deleted: true })
    renderPage(makeSession('nigeria_office_staff'))

    await screen.findByText('Customs delay')
    await userEvent.click(screen.getByRole('button', { name: /withdraw/i }))

    await waitFor(() => expect(announcementsApi.deleteRequest).toHaveBeenCalledWith('req1'))
  })

  it('editing a pending submission calls updateRequest', async () => {
    vi.mocked(announcementsApi.listMine).mockResolvedValue([makeRequest()])
    vi.mocked(announcementsApi.updateRequest).mockResolvedValue(makeRequest({ title: 'Updated title' }))
    renderPage(makeSession('nigeria_office_staff'))

    await screen.findByText('Customs delay')
    await userEvent.click(screen.getByRole('button', { name: /^edit$/i }))

    const titleInput = screen.getByDisplayValue('Customs delay')
    await userEvent.clear(titleInput)
    await userEvent.type(titleInput, 'Updated title')
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() =>
      expect(announcementsApi.updateRequest).toHaveBeenCalledWith('req1', {
        title: 'Updated title',
        body: 'Expect 2-day delays.',
      }),
    )
  })
})
