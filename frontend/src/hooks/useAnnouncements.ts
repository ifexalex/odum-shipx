import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { announcementKeys, customerNotifKeys, staffNotifKeys } from '../api/keys'
import { announcementsApi, type UpdateAnnouncementInput } from '../api/announcements'
import { STALE_30S } from '../lib/queryClient'

/** tenant_admin's review queue for staff-submitted customer announcements. */
export function useAnnouncementPending(enabled = true) {
  return useQuery({
    queryKey: announcementKeys.pending(),
    queryFn: () => announcementsApi.listPending(),
    staleTime: STALE_30S,
    enabled,
  })
}

/** nigeria_office_staff's own submissions, every status. */
export function useMyAnnouncementRequests(enabled = true) {
  return useQuery({
    queryKey: announcementKeys.mine(),
    queryFn: () => announcementsApi.listMine(),
    staleTime: STALE_30S,
    enabled,
  })
}

function invalidateEverythingAnnouncementRelated(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: announcementKeys.all })
  void qc.invalidateQueries({ queryKey: staffNotifKeys.all })
  void qc.invalidateQueries({ queryKey: customerNotifKeys.all })
}

export function useApproveAnnouncement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (requestId: string) => announcementsApi.approve(requestId),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}

export function useRejectAnnouncement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, reason }: { requestId: string; reason?: string }) =>
      announcementsApi.reject(requestId, reason),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}

/** Edit a still-pending request — the requester's own, before tenant_admin reviews it. */
export function useUpdateAnnouncementRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, input }: { requestId: string; input: UpdateAnnouncementInput }) =>
      announcementsApi.updateRequest(requestId, input),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}

/** Withdraw a still-pending request before tenant_admin reviews it. */
export function useDeleteAnnouncementRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (requestId: string) => announcementsApi.deleteRequest(requestId),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}

/** tenant_admin's management list — one entry per send. */
export function useAnnouncementHistory(enabled = true) {
  return useQuery({
    queryKey: announcementKeys.history(),
    queryFn: () => announcementsApi.listHistory(),
    staleTime: STALE_30S,
    enabled,
  })
}

export function useActivateAnnouncement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (groupId: string) => announcementsApi.activate(groupId),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}

export function useDeactivateAnnouncement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (groupId: string) => announcementsApi.deactivate(groupId),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}

/** Edit a sent announcement's title/body — tenant_admin only. */
export function useUpdateAnnouncement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupId, input }: { groupId: string; input: UpdateAnnouncementInput }) =>
      announcementsApi.update(groupId, input),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}

/** Permanently delete a sent announcement — tenant_admin only. */
export function useDeleteAnnouncement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (groupId: string) => announcementsApi.remove(groupId),
    onSuccess: () => invalidateEverythingAnnouncementRelated(qc),
  })
}
