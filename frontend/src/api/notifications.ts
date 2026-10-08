import { apiRequest, apiRequestList } from './client'

export type NotifChannel = 'sms' | 'whatsapp' | 'email'

export type NotifStatus = 'queued' | 'sent' | 'delivered' | 'failed' | 'pending'

export interface NotificationLogEntry {
  id: string
  event_type: string
  channel: NotifChannel
  recipient_name: string | null
  customer_id: string | null
  status: NotifStatus
  provider: string | null
  gateway_response: string | null
  message_body: string | null
  created_at: string
}

export interface NotifLogListParams {
  channel?: NotifChannel
  status?: NotifStatus
  event_type?: string
  customer_id?: string
  /** ISO date (YYYY-MM-DD) — filters on `notification_log.created_at`, inclusive. */
  created_after?: string
  created_before?: string
  limit?: number
  cursor?: string
}

export const notificationLogApi = {
  list: (params: NotifLogListParams = {}) =>
    apiRequestList<NotificationLogEntry>({
      method: 'GET',
      path: '/v1/notifications/log',
      query: params as Record<string, string | number | undefined>,
    }),

  get: (id: string) =>
    apiRequest<NotificationLogEntry>({ method: 'GET', path: `/v1/notifications/log/${id}` }),

  retry: (id: string) =>
    apiRequest<{ queued: boolean }>({ method: 'POST', path: `/v1/notifications/log/${id}/retry`, body: {} }),
}
