import { apiRequest, apiRequestList } from './client'
import type { StaffNotification, StaffNotifListParams } from './staffNotifications'

// Same row shape as the staff bell — both are `staff_notification` rows,
// just visible to a different audience (target_user_id for a customer
// instead of target_role for a staff role). See 15_api_notifications.md's
// "Staff notification bell" section.
export type CustomerNotification = StaffNotification
export type CustomerNotifListParams = StaffNotifListParams

export const customerNotificationsApi = {
  list: ({ unread_only, ...params }: CustomerNotifListParams = {}) =>
    apiRequestList<CustomerNotification>({
      method: 'GET',
      path: '/v1/notifications/customer',
      query: {
        ...(params as Record<string, string | number | undefined>),
        unread_only: unread_only ? 'true' : undefined,
      },
    }),

  unreadCount: () =>
    apiRequest<{ unread_count: number }>({ method: 'GET', path: '/v1/notifications/customer/unread-count' }),

  markRead: (id: string) =>
    apiRequest<CustomerNotification>({ method: 'PATCH', path: `/v1/notifications/customer/${id}/read`, body: {} }),

  markAllRead: () =>
    apiRequest<{ marked_read: number }>({ method: 'PATCH', path: '/v1/notifications/customer/mark-all-read', body: {} }),

  dismiss: (id: string) =>
    apiRequest<CustomerNotification>({ method: 'DELETE', path: `/v1/notifications/customer/${id}` }),

  clearAll: () =>
    apiRequest<{ cleared: number }>({ method: 'DELETE', path: '/v1/notifications/customer/clear-all' }),

  getBanner: () =>
    apiRequest<CustomerNotification | null>({ method: 'GET', path: '/v1/notifications/customer/banner' }),
}
