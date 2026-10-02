import type { JSX } from 'react'
import { Icon } from '../design/components'
import {
  useClearAllCustomerNotif,
  useDismissCustomerNotif,
  useMarkAllCustomerNotifRead,
  useMarkCustomerNotifRead,
  useCustomerNotifList,
} from '../hooks/useCustomerNotifications'
import type { CustomerNotification } from '../api/customerNotifications'
import styles from './StaffNotificationPanel.module.css'

export interface CustomerNotificationPanelProps {
  open: boolean
  onClose: () => void
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const min = Math.floor(ms / 60_000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}

function NotificationRow({
  n,
  onMarkRead,
  onDismiss,
}: {
  n: CustomerNotification
  onMarkRead: (id: string) => void
  onDismiss: (id: string) => void
}): JSX.Element {
  return (
    <div className={[styles.row, n.is_read ? styles.rowRead : styles.rowUnread].join(' ')}>
      <button type="button" className={styles.rowMain} onClick={() => !n.is_read && onMarkRead(n.id)}>
        <span className={styles.dotSlot}>{!n.is_read && <span className={styles.unreadDot} />}</span>
        <span className={styles.rowBody}>
          <span className={styles.rowTitle}>{n.title}</span>
          {n.body && <span className={styles.rowText}>{n.body}</span>}
          <span className={styles.rowTime}>{timeAgo(n.created_at)}</span>
        </span>
      </button>
      <button
        type="button"
        aria-label="Clear notification"
        className={styles.clearBtn}
        onClick={(e) => {
          e.stopPropagation()
          onDismiss(n.id)
        }}
      >
        <Icon name="x" size={12} />
      </button>
    </div>
  )
}

/**
 * The customer portal's bell dropdown — same shape and CSS as
 * StaffNotificationPanel.tsx (kept as a separate small component rather
 * than one shared component with a role switch, since the staff and
 * customer shells never share a render tree), backed by the customer-only
 * `/v1/notifications/customer*` routes.
 *
 * Ground-truth gap found live, reported by the user: they rejected a
 * payment claim and, checking as the customer, "did not see the
 * notification when I logged in" — the customer portal's own bell icon
 * existed (CustomerTopNav.tsx) but was never wired to any data, same gap
 * the staff bell had before it was fixed. Clearing (per-row × and "Clear
 * all") is a further follow-up: "the notification should allow clearing."
 */
export function CustomerNotificationPanel({ open, onClose }: CustomerNotificationPanelProps): JSX.Element | null {
  const { data, isLoading } = useCustomerNotifList({ limit: 20 }, open)
  const markRead = useMarkCustomerNotifRead()
  const markAllRead = useMarkAllCustomerNotifRead()
  const dismiss = useDismissCustomerNotif()
  const clearAll = useClearAllCustomerNotif()

  if (!open) return null

  const items = data?.data ?? []
  const hasUnread = items.some((n) => !n.is_read)

  return (
    <>
      <div className={styles.overlay} onClick={onClose} />
      <div className={styles.panel} role="dialog" aria-label="Notifications">
        <div className={styles.header}>
          <span className={styles.headerTitle}>Notifications</span>
          <div className={styles.headerActions}>
            {hasUnread && (
              <button
                type="button"
                className={styles.markAllBtn}
                onClick={() => markAllRead.mutate()}
                disabled={markAllRead.isPending}
              >
                Mark all read
              </button>
            )}
            {items.length > 0 && (
              <button
                type="button"
                className={styles.markAllBtn}
                onClick={() => clearAll.mutate()}
                disabled={clearAll.isPending}
              >
                Clear all
              </button>
            )}
          </div>
        </div>
        <div className={styles.list}>
          {isLoading && <div className={styles.empty}>Loading…</div>}
          {!isLoading && items.length === 0 && (
            <div className={styles.empty}>
              <Icon name="bell" size={20} color="var(--color-ink-4)" />
              <span>No notifications yet.</span>
            </div>
          )}
          {items.map((n) => (
            <NotificationRow
              key={n.id}
              n={n}
              onMarkRead={(id) => markRead.mutate(id)}
              onDismiss={(id) => dismiss.mutate(id)}
            />
          ))}
        </div>
      </div>
    </>
  )
}
