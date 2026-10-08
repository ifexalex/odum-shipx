import { apiRequest, apiRequestList } from './client'

export interface StaffNotification {
  id: string
  tenant_id: string
  target_role: string | null
  target_user_id: string | null
  event_type: string
  entity_type: string
  entity_id: string | null
  title: string
  body: string | null
  is_read: boolean
  created_at: string
}

export interface StaffNotifListParams {
  unread_only?: boolean
  limit?: number
  cursor?: string
}

export const staffNotificationsApi = {
  list: ({ unread_only, ...params }: StaffNotifListParams = {}) =>
    apiRequestList<StaffNotification>({
      method: 'GET',
      path: '/v1/notifications/staff',
      query: {
        ...(params as Record<string, string | number | undefined>),
        unread_only: unread_only ? 'true' : undefined,
      },
    }),

  unreadCount: () =>
    apiRequest<{ unread_count: number }>({ method: 'GET', path: '/v1/notifications/staff/unread-count' }),

  markRead: (id: string) =>
    apiRequest<StaffNotification>({ method: 'PATCH', path: `/v1/notifications/staff/${id}/read`, body: {} }),

  markAllRead: () =>
    apiRequest<{ marked_read: number }>({ method: 'PATCH', path: '/v1/notifications/staff/mark-all-read', body: {} }),

  /** Clears (dismisses) one notification for the caller only — a role-broadcast
   * notification cleared by one recipient stays visible to every other one. */
  dismiss: (id: string) =>
    apiRequest<StaffNotification>({ method: 'DELETE', path: `/v1/notifications/staff/${id}` }),

  clearAll: () =>
    apiRequest<{ cleared: number }>({ method: 'DELETE', path: '/v1/notifications/staff/clear-all' }),

  /** The single announcement (if any) to show as a page banner — null when
   * nothing is currently active. */
  getBanner: () => apiRequest<StaffNotification | null>({ method: 'GET', path: '/v1/notifications/staff/banner' }),
}
