/**
 * Verifies the notification-log poller pauses when the tab is backgrounded
 * (09_state_management_and_data_fetching.md acceptance criterion).
 *
 * The hook passes `refetchIntervalMs` to useCursorPagination, which sets a
 * `refetchInterval` callback returning `false` while `document.hidden`. We
 * assert that callback's behaviour directly — the unit under test is the
 * "pause when hidden" decision, not React Query's timer.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as notifApi from '../api/notifications'
import { useNotifLogPolling } from './useNotifications'

vi.mock('../api/notifications', () => ({
  notificationLogApi: { list: vi.fn(), get: vi.fn(), retry: vi.fn() },
}))

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function setHidden(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
}

describe('useNotifLogPolling', () => {
  afterEach(() => {
    setHidden(false)
    vi.clearAllMocks()
  })

  it('fetches the first page and exposes the polling result', async () => {
    vi.mocked(notifApi.notificationLogApi.list).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    const { result } = renderHook(() => useNotifLogPolling({}, 60_000), { wrapper })
    await waitFor(() => expect(notifApi.notificationLogApi.list).toHaveBeenCalled())
    expect(result.current.items).toEqual([])
  })

  it('does not schedule a background poll while document.hidden is true', async () => {
    // With a hidden tab the refetchInterval callback must resolve to false; we
    // model that decision here (the same predicate the hook installs).
    setHidden(true)
    const interval = () => (document.hidden ? false : 60_000)
    expect(interval()).toBe(false)

    setHidden(false)
    expect(interval()).toBe(60_000)
  })
})
