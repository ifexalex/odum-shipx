import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notifLogKeys } from '../api/keys'
import { notificationLogApi, type NotifLogListParams } from '../api/notifications'
import { STALE_30S } from '../lib/queryClient'
import { useCursorPagination } from './useCursorPagination'

export function useNotifLogList(params: NotifLogListParams = {}) {
  return useCursorPagination(
    notifLogKeys.list(params as Record<string, unknown>),
    (cursor) => notificationLogApi.list({ ...params, cursor }),
    { staleTime: STALE_30S },
  )
}

export function useNotifLogEntry(id: string) {
  return useQuery({
    queryKey: notifLogKeys.detail(id),
    queryFn: () => notificationLogApi.get(id),
    enabled: !!id,
    staleTime: STALE_30S,
  })
}

export function useRetryNotification(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => notificationLogApi.retry(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: notifLogKeys.all })
    },
  })
}

/**
 * Polls the notification log while the tab is focused; pauses when backgrounded.
 * Polling cadence defaults to 60s (delivery is near-real-time but not urgent).
 */
export function useNotifLogPolling(params: NotifLogListParams = {}, intervalMs = 60_000) {
  return useCursorPagination(
    notifLogKeys.list(params as Record<string, unknown>),
    (cursor) => notificationLogApi.list({ ...params, cursor }),
    { staleTime: STALE_30S, refetchIntervalMs: intervalMs },
  )
}
