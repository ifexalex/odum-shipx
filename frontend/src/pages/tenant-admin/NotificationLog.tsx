import { useQuery } from '@tanstack/react-query'
import { useMemo, useState, type JSX } from 'react'
import { notificationLogApi, type NotifChannel, type NotifStatus, type NotificationLogEntry } from '../../api/notifications'
import { notifLogKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { useNotifLogPolling } from '../../hooks/useNotifications'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import {  Button, Card, Chip, DateRangeFilter, Icon, ListFooter, Mono, StatusBadge, Table, UserCell, IconButton, Pressable, SearchField, EmptyState, ErrorState } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './NotificationLog.module.css'
import { formatDateTime } from '../../lib/format'
import { toast } from '../../design/toast'

const CHANNEL_FILTERS: Array<{ key: NotifChannel; label: string }> = [
  { key: 'sms',      label: 'SMS' },
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'email',    label: 'Email' },
]

const STATUS_FILTER_OPTS: Array<NotifStatus | 'all'> = ['all', 'queued', 'sent', 'delivered', 'failed', 'pending']

const CHANNEL_COLOR: Record<NotifChannel, string> = {
  sms:      'var(--color-info)',
  whatsapp: 'var(--color-success)',
  email:    'var(--color-accent)',
}

const EVENT_LABELS: Record<string, string> = {
  payment_due:    'Payment due',
  shipment_update:'Status update',
  release_note:   'Release note',
  claim_filed:    'Claim filed',
  claim_resolved: 'Claim resolved',
  refund_approved:'Refund approved',
}

function fmtTs(ts: string): string {
  return formatDateTime(ts, { year: false })
}

function LogStat({ label, value, sub, color }: { label: string; value: number; sub?: string; color: string }): JSX.Element {
  return (
    <div className={styles.logStat}>
      <span className={styles.logStatValue} style={{ color }}>{value}</span>
      <span className={styles.logStatLabel}>{label}</span>
      {sub && <span className={styles.logStatSub}>({sub})</span>}
    </div>
  )
}

export function NotificationLog(): JSX.Element {
  const [channelFilter, setChannelFilter] = useState<NotifChannel | null>(null)
  const [statusFilter, setStatusFilter] = useState<NotifStatus | 'all'>('all')
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [retryingId, setRetryingId] = useState<string | null>(null)
  const [selectedLog, setSelectedLog] = useState<NotificationLogEntry | null>(null)
  // "Sent within" — null/'' means no date filter, same opt-in-only rationale
  // as BillingList/ContainerList/ClaimList's date filters.
  const sentRange = useDateRangeFilter()

  useTopBarSlot({
    actions: <Button variant="secondary" icon="download">Export</Button>,
  })

  // Stats window — a larger cached sample, separate from the live table below.
  // On `lookup`, not `list`: `list` belongs to the infinite useNotifLogPolling
  // below, and a plain useQuery there caches an incompatible shape. The old
  // `{ scope: 'stats' }` sentinel avoided the clash only because no filter
  // combination happened to produce it; the params now describe the request.
  const { data: allData } = useQuery({
    queryKey: notifLogKeys.lookup({ limit: 500 }),
    queryFn: () => notificationLogApi.list({ limit: 500 }),
    staleTime: STALE_5_MIN,
  })
  const allLogs = useMemo(() => allData?.data ?? [], [allData])

  // Live table — polls every 60s while the tab is visible, pauses when hidden.
  const {
    items: logs, isLoading: loading, error, hasMore, loadMore, isFetchingMore, refetch, totalCount,
  } = useNotifLogPolling({
    ...(channelFilter ? { channel: channelFilter } : {}),
    ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
    ...(sentRange.createdAfter ? { created_after: sentRange.createdAfter } : {}),
    ...(sentRange.createdBefore ? { created_before: sentRange.createdBefore } : {}),
  })

  const stats = useMemo(() => ({
    sent:      allLogs.filter((l) => l.status !== 'queued').length,
    delivered: allLogs.filter((l) => l.status === 'delivered').length,
    failed:    allLogs.filter((l) => l.status === 'failed').length,
    pending:   allLogs.filter((l) => l.status === 'queued' || l.status === 'pending').length,
    total:     allLogs.length,
  }), [allLogs])

  const channelCounts = useMemo(() =>
    Object.fromEntries(
      CHANNEL_FILTERS.map(({ key }) => [key, allLogs.filter((l) => l.channel === key).length])
    ) as Record<NotifChannel, number>,
  [allLogs])

  async function handleRetry(entry: NotificationLogEntry): Promise<void> {
    setRetryingId(entry.id)
    try {
      await notificationLogApi.retry(entry.id)
      toast.success('Message queued to send again')
      refetch()
    } catch {
      // ignore — retry failure is non-critical
    } finally {
      setRetryingId(null)
    }
  }

  // Client-side search filter
  const displayed = search
    ? logs.filter((l) =>
        (l.recipient_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
        l.event_type.toLowerCase().includes(search.toLowerCase())
      )
    : logs

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <ErrorState compact title="Couldn't load log" error={error} onRetry={() => void refetch()} />
        </div>
      )}

      {/* Stats bar */}
      <Card padding="default" style={{ marginBottom: 'var(--space-4)' }}>
        <div className={styles.statsBar}>
          <span className={styles.statsLabel}>Last 30 days</span>
          <LogStat label="Sent"      value={stats.sent}      color="var(--color-info)" />
          <LogStat label="Delivered" value={stats.delivered}
            sub={stats.sent > 0 ? `${((stats.delivered / stats.sent) * 100).toFixed(1)}%` : undefined}
            color="var(--color-success)" />
          <LogStat label="Failed"    value={stats.failed}    color="var(--color-error)" />
          <LogStat label="Pending"   value={stats.pending}   color="var(--color-ink-4)" />
        </div>
      </Card>

      {/* Filter bar */}
      <Card padding="default" style={{ marginBottom: 'var(--space-4)' }}>
        <div className={styles.filterRow}>
          <div className={styles.chips}>
            <Chip active={channelFilter === null} onClick={() => setChannelFilter(null)}>
              All channels
            </Chip>
            {CHANNEL_FILTERS.map(({ key, label }) => (
              <Chip key={key} active={channelFilter === key} onClick={() => setChannelFilter(key)}>
                {label}
                {allLogs.length > 0 && (
                  <span className={styles.chipCount}>{channelCounts[key] ?? 0}</span>
                )}
              </Chip>
            ))}
          </div>
          <div className={styles.statusDropdown}>
            <Button
              variant="secondary"
              trailingIcon="chevdown"
              onClick={() => setStatusDropdownOpen((o) => !o)}
            >
              {statusFilter === 'all' ? 'Status: All' : `Status: ${statusFilter.charAt(0).toUpperCase() + statusFilter.slice(1)}`}
            </Button>
            {statusDropdownOpen && (
              <div className={styles.dropdown}>
                {STATUS_FILTER_OPTS.map((s) => (
                  <Pressable
                    key={s}
                    type="button"
                    className={[styles.dropdownItem, statusFilter === s ? styles.dropdownItemActive : ''].filter(Boolean).join(' ')}
                    onClick={() => { setStatusFilter(s); setStatusDropdownOpen(false) }}
                  >
                    {s === 'all' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
                  </Pressable>
                ))}
              </div>
            )}
          </div>
          <SearchField label="Search notifications" placeholder="Customer, event type, message…" value={search} onChange={setSearch} />
          <DateRangeFilter label="Sent" range={sentRange} />
        </div>
      </Card>

      {/* Table */}
      <Card padding="none">
        <Table
          columns={[
            { title: 'Sent at' },
            { title: 'Customer' },
            { title: 'Channel' },
            { title: 'Event type' },
            { title: 'Message preview' },
            { title: 'Status' },
            { title: '', width: '100px' },
          ]}
          rows={displayed.map((entry) => ({
            suspended: entry.status === 'failed',
            cells: [
              <Mono key="ts" color="var(--color-ink-2)">{fmtTs(entry.created_at)}</Mono>,
              entry.recipient_name
                ? <UserCell key="cust" name={entry.recipient_name} email="" />
                : <span key="cust" style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-sm)' }}>—</span>,
              <div key="ch" className={styles.channelCell}>
                <Icon
                  name={entry.channel === 'email' ? 'mail' : 'phone'}
                  size={13}
                  color={CHANNEL_COLOR[entry.channel]}
                />
                <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-2)' }}>
                  {entry.channel === 'whatsapp' ? 'WhatsApp' : entry.channel.toUpperCase()}
                </span>
              </div>,
              <span key="ev" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-2)' }}>
                {EVENT_LABELS[entry.event_type] ?? entry.event_type.replace(/_/g, ' ')}
              </span>,
              <span key="msg" className={styles.msgPreview}>
                {entry.message_body ? `"${entry.message_body.slice(0, 60)}${entry.message_body.length > 60 ? '…' : ''}"` : '—'}
              </span>,
              <StatusBadge key="status" size="sm" kind="notification" status={entry.status} />,
              <div key="action" className={styles.rowActions}>
                {entry.status === 'failed' && (
                  <Button variant="secondary" size="sm" icon="refresh"
                    loading={retryingId === entry.id}
                    onClick={() => void handleRetry(entry)}>
                    Retry
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => setSelectedLog(entry)}>
                  View
                </Button>
              </div>,
            ],
          }))}
          loading={loading}
          emptyState={!loading && displayed.length === 0 ? <EmptyState compact title="No notifications logged yet" /> : undefined}
        />
      </Card>

      <ListFooter
        shown={logs.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="notifications"
      />

      {/* Detail modal */}
      {selectedLog && (
        <div className={styles.modalOverlay} onClick={() => setSelectedLog(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h3 className={styles.modalTitle}>Notification detail</h3>
                <p className={styles.modalSub}>
                  {selectedLog.channel === 'whatsapp' ? 'WhatsApp' : selectedLog.channel.toUpperCase()}
                  {' · '}
                  {EVENT_LABELS[selectedLog.event_type] ?? selectedLog.event_type}
                  {' · '}
                  {fmtTs(selectedLog.created_at)}
                </p>
              </div>
              <IconButton icon="x" label="Close" size="sm" onClick={() => setSelectedLog(null)} />
            </div>
            <div className={styles.modalBody}>
              <div className={styles.kvp}><span>Recipient</span><span>{selectedLog.recipient_name ?? '—'}</span></div>
              <div className={styles.kvp}><span>Channel</span><span>{selectedLog.channel}</span></div>
              <div className={styles.kvp}><span>Event type</span><span>{selectedLog.event_type}</span></div>
              <div className={styles.kvp}><span>Status</span>
                <StatusBadge size="sm" kind="notification" status={selectedLog.status} />
              </div>
              <div className={styles.kvp}><span>Provider</span><span>{selectedLog.provider ?? '—'}</span></div>
              {selectedLog.message_body && (
                <div className={styles.msgBubbleWrap}>
                  <div className={styles.msgBubble}>{selectedLog.message_body}</div>
                </div>
              )}
              {selectedLog.gateway_response && (
                <div className={styles.kvp}>
                  <span>Provider response</span>
                  <span className={styles.gatewayResp}>{selectedLog.gateway_response}</span>
                </div>
              )}
            </div>
            <div className={styles.modalFooter}>
              {selectedLog.status === 'failed' && (
                <Button variant="primary" icon="refresh"
                  loading={retryingId === selectedLog.id}
                  onClick={() => void handleRetry(selectedLog)}>
                  Resend
                </Button>
              )}
              <Button variant="secondary" onClick={() => setSelectedLog(null)}>Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
