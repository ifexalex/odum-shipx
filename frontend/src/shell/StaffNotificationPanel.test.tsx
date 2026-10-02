import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { staffNotificationsApi } from '../api/staffNotifications'
import { StaffNotificationPanel } from './StaffNotificationPanel'

vi.mock('../api/staffNotifications', () => ({
  staffNotificationsApi: {
    list: vi.fn(),
    unreadCount: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
    dismiss: vi.fn(),
    clearAll: vi.fn(),
  },
}))

function makeNotif(overrides = {}) {
  return {
    id: 'n1',
    tenant_id: 't1',
    target_role: 'nigeria_office_staff',
    target_user_id: null,
    event_type: 'payment_claim_submitted',
    entity_type: 'payment_claim',
    entity_id: 'claim-1',
    title: 'New payment claim submitted',
    body: 'A payment claim for NGN 50000.00 is awaiting review.',
    is_read: false,
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...overrides,
  }
}

function renderPanel(open = true, onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <StaffNotificationPanel open={open} onClose={onClose} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(staffNotificationsApi.list).mockReset()
  vi.mocked(staffNotificationsApi.markRead).mockReset()
  vi.mocked(staffNotificationsApi.markAllRead).mockReset()
  vi.mocked(staffNotificationsApi.dismiss).mockReset()
  vi.mocked(staffNotificationsApi.clearAll).mockReset()
})

describe('StaffNotificationPanel', () => {
  it('renders nothing when closed', () => {
    renderPanel(false)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows an empty state when there are no notifications', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPanel()
    expect(await screen.findByText(/no notifications yet/i)).toBeInTheDocument()
  })

  it('renders notification rows with title, body, and an unread indicator', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPanel()
    expect(await screen.findByText('New payment claim submitted')).toBeInTheDocument()
    expect(screen.getByText(/awaiting review/)).toBeInTheDocument()
  })

  it('clicking an unread row marks it read', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(staffNotificationsApi.markRead).mockResolvedValue(makeNotif({ is_read: true }))
    renderPanel()

    const row = await screen.findByText('New payment claim submitted')
    await userEvent.click(row)

    await waitFor(() => expect(staffNotificationsApi.markRead).toHaveBeenCalledWith('n1'))
  })

  it('"Mark all read" only appears when something is unread, and calls the API', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(staffNotificationsApi.markAllRead).mockResolvedValue({ marked_read: 1 })
    renderPanel()

    const btn = await screen.findByRole('button', { name: /mark all read/i })
    await userEvent.click(btn)

    await waitFor(() => expect(staffNotificationsApi.markAllRead).toHaveBeenCalled())
  })

  it('does not show "Mark all read" when everything is already read', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [makeNotif({ is_read: true })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPanel()

    await screen.findByText('New payment claim submitted')
    expect(screen.queryByRole('button', { name: /mark all read/i })).toBeNull()
  })

  it('clicking the overlay calls onClose', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    const onClose = vi.fn()
    renderPanel(true, onClose)
    await screen.findByText(/no notifications yet/i)

    // Overlay is the sibling before the dialog panel — click it directly.
    const dialog = screen.getByRole('dialog')
    const overlay = dialog.previousSibling as HTMLElement
    await userEvent.click(overlay)

    expect(onClose).toHaveBeenCalled()
  })

  it('clicking the clear button on a row dismisses it without marking read via the row click', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(staffNotificationsApi.dismiss).mockResolvedValue(makeNotif({ is_read: true }))
    renderPanel()

    await screen.findByText('New payment claim submitted')
    const clearBtn = screen.getByRole('button', { name: /clear notification/i })
    await userEvent.click(clearBtn)

    await waitFor(() => expect(staffNotificationsApi.dismiss).toHaveBeenCalledWith('n1'))
    expect(staffNotificationsApi.markRead).not.toHaveBeenCalled()
  })

  it('"Clear all" only appears when there are notifications, and calls the API', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(staffNotificationsApi.clearAll).mockResolvedValue({ cleared: 1 })
    renderPanel()

    const btn = await screen.findByRole('button', { name: /^clear all$/i })
    await userEvent.click(btn)

    await waitFor(() => expect(staffNotificationsApi.clearAll).toHaveBeenCalled())
  })

  it('does not show "Clear all" when there are no notifications', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPanel()

    await screen.findByText(/no notifications yet/i)
    expect(screen.queryByRole('button', { name: /^clear all$/i })).toBeNull()
  })

  it('never shows announcement composing/management controls — that moved to its own page', async () => {
    vi.mocked(staffNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPanel()

    await screen.findByText(/no notifications yet/i)
    expect(screen.queryByRole('button', { name: /new announcement/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /manage announcements/i })).toBeNull()
  })
})
