import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { customerNotifKeys } from '../api/keys'
import { customerNotificationsApi, type CustomerNotifListParams } from '../api/customerNotifications'
import { STALE_30S } from '../lib/queryClient'

// Mirrors useStaffNotifications.ts exactly — same underlying rows, different
// audience. See customerNotifications.ts's own note on why these are kept
// as separate API/hook modules rather than one shared with a role switch:
// the two portals' components never import from each other's tree.

/** Polls the unread count for the customer portal's bell badge while the
 * tab is focused; pauses when backgrounded. */
export function useCustomerNotifUnreadCount(enabled = true, intervalMs = 30_000) {
  return useQuery({
    queryKey: customerNotifKeys.unreadCount(),
    queryFn: () => customerNotificationsApi.unreadCount(),
    staleTime: STALE_30S,
    enabled,
    refetchInterval: () => (typeof document !== 'undefined' && document.hidden ? false : intervalMs),
    refetchIntervalInBackground: false,
  })
}

/** The bell dropdown's list — a fixed recent page, not infinite-scrolled.
 * `enabled` should be tied to the panel's own open state so a mounted-but-
 * closed bell doesn't fetch in the background. */
export function useCustomerNotifList(params: CustomerNotifListParams = {}, enabled = true) {
  return useQuery({
    queryKey: customerNotifKeys.list(params as Record<string, unknown>),
    queryFn: () => customerNotificationsApi.list(params),
    staleTime: STALE_30S,
    enabled,
  })
}

export function useMarkCustomerNotifRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => customerNotificationsApi.markRead(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: customerNotifKeys.all })
    },
  })
}

export function useMarkAllCustomerNotifRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => customerNotificationsApi.markAllRead(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: customerNotifKeys.all })
    },
  })
}

export function useDismissCustomerNotif() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => customerNotificationsApi.dismiss(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: customerNotifKeys.all })
    },
  })
}

export function useClearAllCustomerNotif() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => customerNotificationsApi.clearAll(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: customerNotifKeys.all })
    },
  })
}

/** Polls for the active announcement banner (if any) while the tab is
 * focused — mirrors useStaffBanner exactly. */
export function useCustomerBanner(enabled = true, intervalMs = 60_000) {
  return useQuery({
    queryKey: customerNotifKeys.banner(),
    queryFn: () => customerNotificationsApi.getBanner(),
    staleTime: STALE_30S,
    enabled,
    refetchInterval: () => (typeof document !== 'undefined' && document.hidden ? false : intervalMs),
    refetchIntervalInBackground: false,
  })
}
