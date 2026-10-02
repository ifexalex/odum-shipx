import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { staffNotifKeys } from '../api/keys'
import { staffNotificationsApi, type StaffNotifListParams } from '../api/staffNotifications'
import { STALE_30S } from '../lib/queryClient'

/**
 * Polls the unread count for the TopBar bell badge while the tab is
 * focused; pauses when backgrounded (see useNotifLogPolling's identical
 * rationale). 30s cadence — the bell should feel "live" without hammering
 * the API on every render.
 */
export function useStaffNotifUnreadCount(enabled = true, intervalMs = 30_000) {
  return useQuery({
    queryKey: staffNotifKeys.unreadCount(),
    queryFn: () => staffNotificationsApi.unreadCount(),
    staleTime: STALE_30S,
    enabled,
    refetchInterval: () => (typeof document !== 'undefined' && document.hidden ? false : intervalMs),
    refetchIntervalInBackground: false,
  })
}

/** The bell dropdown's list — a fixed recent page, not infinite-scrolled;
 * the panel is a small popup, not a full list page. `enabled` defaults to
 * true but should be tied to the panel's own open state by the caller, so
 * a mounted-but-closed bell doesn't fetch in the background. */
export function useStaffNotifList(params: StaffNotifListParams = {}, enabled = true) {
  return useQuery({
    queryKey: staffNotifKeys.list(params as Record<string, unknown>),
    queryFn: () => staffNotificationsApi.list(params),
    staleTime: STALE_30S,
    enabled,
  })
}

export function useMarkStaffNotifRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => staffNotificationsApi.markRead(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: staffNotifKeys.all })
    },
  })
}

export function useMarkAllStaffNotifRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => staffNotificationsApi.markAllRead(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: staffNotifKeys.all })
    },
  })
}

export function useDismissStaffNotif() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => staffNotificationsApi.dismiss(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: staffNotifKeys.all })
    },
  })
}

export function useClearAllStaffNotif() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => staffNotificationsApi.clearAll(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: staffNotifKeys.all })
    },
  })
}

/** Polls for the active announcement banner (if any) while the tab is
 * focused — same cadence/pause-when-hidden pattern as the unread count, so
 * a newly-sent announcement reaches an already-open tab without a reload. */
export function useStaffBanner(enabled = true, intervalMs = 60_000) {
  return useQuery({
    queryKey: staffNotifKeys.banner(),
    queryFn: () => staffNotificationsApi.getBanner(),
    staleTime: STALE_30S,
    enabled,
    refetchInterval: () => (typeof document !== 'undefined' && document.hidden ? false : intervalMs),
    refetchIntervalInBackground: false,
  })
}
