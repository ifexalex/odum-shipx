import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { customerNotificationsApi } from '../api/customerNotifications'
import { CustomerNotificationPanel } from './CustomerNotificationPanel'

vi.mock('../api/customerNotifications', () => ({
  customerNotificationsApi: {
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
    target_role: null,
    target_user_id: 'portal-user-001',
    event_type: 'payment_claim_rejected',
    entity_type: 'payment_claim',
    entity_id: 'claim-1',
    title: 'Payment claim rejected',
    body: 'Your payment claim of NGN 50000.00 was not confirmed. Reason: we did not receive your payment',
    is_read: false,
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...overrides,
  }
}

function renderPanel(open = true, onClose = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <CustomerNotificationPanel open={open} onClose={onClose} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(customerNotificationsApi.list).mockReset()
  vi.mocked(customerNotificationsApi.markRead).mockReset()
  vi.mocked(customerNotificationsApi.markAllRead).mockReset()
  vi.mocked(customerNotificationsApi.dismiss).mockReset()
  vi.mocked(customerNotificationsApi.clearAll).mockReset()
})

describe('CustomerNotificationPanel', () => {
  it('renders nothing when closed', () => {
    renderPanel(false)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows an empty state when there are no notifications', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPanel()
    expect(await screen.findByText(/no notifications yet/i)).toBeInTheDocument()
  })

  it('renders the rejection reason from the exact scenario reported live', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPanel()
    expect(await screen.findByText('Payment claim rejected')).toBeInTheDocument()
    expect(screen.getByText(/we did not receive your payment/)).toBeInTheDocument()
  })

  it('clicking an unread row marks it read', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(customerNotificationsApi.markRead).mockResolvedValue(makeNotif({ is_read: true }))
    renderPanel()

    const row = await screen.findByText('Payment claim rejected')
    await userEvent.click(row)

    await waitFor(() => expect(customerNotificationsApi.markRead).toHaveBeenCalledWith('n1'))
  })

  it('"Mark all read" only appears when something is unread, and calls the API', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(customerNotificationsApi.markAllRead).mockResolvedValue({ marked_read: 1 })
    renderPanel()

    const btn = await screen.findByRole('button', { name: /mark all read/i })
    await userEvent.click(btn)

    await waitFor(() => expect(customerNotificationsApi.markAllRead).toHaveBeenCalled())
  })

  it('does not show "Mark all read" when everything is already read', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [makeNotif({ is_read: true })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPanel()

    await screen.findByText('Payment claim rejected')
    expect(screen.queryByRole('button', { name: /mark all read/i })).toBeNull()
  })

  it('clicking the overlay calls onClose', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    const onClose = vi.fn()
    renderPanel(true, onClose)
    await screen.findByText(/no notifications yet/i)

    const dialog = screen.getByRole('dialog')
    const overlay = dialog.previousSibling as HTMLElement
    await userEvent.click(overlay)

    expect(onClose).toHaveBeenCalled()
  })

  it('clicking the clear button on a row dismisses it without marking read via the row click', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(customerNotificationsApi.dismiss).mockResolvedValue(makeNotif({ is_read: true }))
    renderPanel()

    await screen.findByText('Payment claim rejected')
    const clearBtn = screen.getByRole('button', { name: /clear notification/i })
    await userEvent.click(clearBtn)

    await waitFor(() => expect(customerNotificationsApi.dismiss).toHaveBeenCalledWith('n1'))
    expect(customerNotificationsApi.markRead).not.toHaveBeenCalled()
  })

  it('"Clear all" only appears when there are notifications, and calls the API', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    vi.mocked(customerNotificationsApi.clearAll).mockResolvedValue({ cleared: 1 })
    renderPanel()

    const btn = await screen.findByRole('button', { name: /^clear all$/i })
    await userEvent.click(btn)

    await waitFor(() => expect(customerNotificationsApi.clearAll).toHaveBeenCalled())
  })

  it('does not show "Clear all" when there are no notifications', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPanel()

    await screen.findByText(/no notifications yet/i)
    expect(screen.queryByRole('button', { name: /^clear all$/i })).toBeNull()
  })

  it('never shows a "New announcement" trigger — customers cannot send announcements', async () => {
    vi.mocked(customerNotificationsApi.list).mockResolvedValue({
      data: [makeNotif()],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPanel()

    await screen.findByText('Payment claim rejected')
    expect(screen.queryByRole('button', { name: /new announcement/i })).toBeNull()
  })
})
