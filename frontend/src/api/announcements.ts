import { apiRequest, apiRequestList } from './client'

export type AnnouncementAudience = 'all_staff' | 'all_customers'

export interface SendAnnouncementInput {
  title: string
  body?: string
  audience: AnnouncementAudience
}

// tenant_admin gets an immediate send; nigeria_office_staff targeting
// customers gets a pending request instead — see 15_api_notifications.md's
// "staff customer-announcements now require tenant_admin approval" section.
export type SendAnnouncementResult =
  | { status: 'sent'; audience: AnnouncementAudience; notifications_created: number }
  | { status: 'pending'; request_id: string; audience: AnnouncementAudience }

export interface AnnouncementRequest {
  id: string
  tenant_id: string
  title: string
  body: string | null
  audience: AnnouncementAudience
  status: 'pending' | 'approved' | 'rejected'
  requested_by: string
  reviewed_by: string | null
  reviewed_at: string | null
  rejection_reason: string | null
  created_at: string
}

export interface AnnouncementHistoryEntry {
  announcement_group_id: string
  title: string
  body: string | null
  audience: AnnouncementAudience
  banner_active: boolean
  created_at: string
}

export interface UpdateAnnouncementInput {
  title: string
  body?: string
}

// Manual broadcast composed by tenant_admin/nigeria_office_staff, managed on
// its own dedicated Announcements page (not the notification bell popup) —
// delivered via the same staff_notification bell as every system-triggered
// event, and (once active) as a page banner. See 15_api_notifications.md's
// "Announcements page" section.
export const announcementsApi = {
  send: (input: SendAnnouncementInput) =>
    apiRequest<SendAnnouncementResult>({ method: 'POST', path: '/v1/notifications/announce', body: input }),

  // tenant_admin review queue for staff-submitted customer announcements.
  listPending: () =>
    apiRequestList<AnnouncementRequest>({ method: 'GET', path: '/v1/notifications/announcements/pending' }),

  // nigeria_office_staff's own submissions, every status.
  listMine: () => apiRequest<AnnouncementRequest[]>({ method: 'GET', path: '/v1/notifications/announcements/mine' }),

  approve: (requestId: string) =>
    apiRequest<{ status: string; audience: AnnouncementAudience; notifications_created: number }>({
      method: 'PATCH',
      path: `/v1/notifications/announcements/requests/${requestId}/approve`,
    }),

  reject: (requestId: string, reason?: string) =>
    apiRequest<{ status: string }>({
      method: 'PATCH',
      path: `/v1/notifications/announcements/requests/${requestId}/reject`,
      body: { reason },
    }),

  // Edit/withdraw — nigeria_office_staff, their own request, only while pending.
  updateRequest: (requestId: string, input: UpdateAnnouncementInput) =>
    apiRequest<AnnouncementRequest>({
      method: 'PATCH',
      path: `/v1/notifications/announcements/requests/${requestId}`,
      body: input,
    }),

  deleteRequest: (requestId: string) =>
    apiRequest<{ deleted: boolean }>({
      method: 'DELETE',
      path: `/v1/notifications/announcements/requests/${requestId}`,
    }),

  // tenant_admin management list — one entry per send, newest first.
  listHistory: () => apiRequest<AnnouncementHistoryEntry[]>({ method: 'GET', path: '/v1/notifications/announcements' }),

  activate: (groupId: string) =>
    apiRequest<{ announcement_group_id: string; banner_active: boolean }>({
      method: 'PATCH',
      path: `/v1/notifications/announcements/${groupId}/activate`,
    }),

  deactivate: (groupId: string) =>
    apiRequest<{ announcement_group_id: string; banner_active: boolean }>({
      method: 'PATCH',
      path: `/v1/notifications/announcements/${groupId}/deactivate`,
    }),

  // Edit/delete a sent announcement — tenant_admin only.
  update: (groupId: string, input: UpdateAnnouncementInput) =>
    apiRequest<{ announcement_group_id: string; title: string; body: string | null }>({
      method: 'PATCH',
      path: `/v1/notifications/announcements/${groupId}`,
      body: input,
    }),

  remove: (groupId: string) =>
    apiRequest<{ deleted: boolean }>({ method: 'DELETE', path: `/v1/notifications/announcements/${groupId}` }),
}
