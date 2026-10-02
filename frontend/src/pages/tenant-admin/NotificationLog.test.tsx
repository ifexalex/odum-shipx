import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { notificationLogApi, type NotificationLogEntry } from '../../api/notifications'
import { NotificationLog } from './NotificationLog'

vi.mock('../../api/notifications', () => ({
  notificationLogApi: { list: vi.fn(), get: vi.fn(), retry: vi.fn() },
}))

const LOG_STUB: NotificationLogEntry = {
  id: 'log-1',
  event_type: 'payment_due',
  channel: 'sms',
  recipient_name: 'Ngozi Okonkwo',
  customer_id: 'cust-1',
  status: 'delivered',
  provider: 'termii',
  gateway_response: null,
  message_body: 'Your payment is due',
  created_at: '2026-06-15T10:00:00Z',
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><NotificationLog /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => { vi.mocked(notificationLogApi.list).mockReset() })

describe('NotificationLog', () => {
  it('renders notification log entries from the API', async () => {
    vi.mocked(notificationLogApi.list).mockResolvedValue({
      data: [LOG_STUB],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('Ngozi Okonkwo')).toBeInTheDocument())
  })

  // Ground-truth gap found live, reported by the user: "I want all the
  // filters that use calendar to allow date range... check all pages where
  // we are using calendar filter." The "Last 30 days" button here was a
  // static label with no onClick at all, and neither the frontend param
  // type nor the backend (`notification/repository.py::list_logs`) supported
  // a date filter to back it.
  it('a date-range preset and a custom From/To both filter by created_after/created_before', async () => {
    vi.mocked(notificationLogApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    renderPage()
    await waitFor(() => expect(notificationLogApi.list).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(await screen.findByRole('option', { name: /last 30 days/i }))
    await waitFor(() =>
      expect(notificationLogApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ created_after: expect.any(String) }),
      ),
    )

    await userEvent.type(screen.getByLabelText('From'), '2026-01-01')
    await userEvent.type(screen.getByLabelText('To'), '2026-01-31')
    await waitFor(() =>
      expect(notificationLogApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ created_after: '2026-01-01', created_before: '2026-01-31' }),
      ),
    )
  })
})
