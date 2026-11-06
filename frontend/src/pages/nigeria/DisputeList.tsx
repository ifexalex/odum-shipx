import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { isTerminalDisputeStatus } from '../../api/billingRules'
import { type CBMDisputeStatus } from '../../api/billing'
import { useDisputeList } from '../../hooks/useBilling'
import { Badge, Banner, Card, Chip, Mono, Table, ViewLink, ListFooter, type BadgeVariant } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import { useNow } from '../../hooks/useNow'
import styles from './DisputeList.module.css'

const _DISPUTE_SLA_DAYS = 7

function SLACountdown({
  submittedAt,
  status,
  now,
}: {
  submittedAt: string
  status: CBMDisputeStatus
  now: number
}): JSX.Element {
  if (isTerminalDisputeStatus(status)) return <span>—</span>
  const submitted = new Date(submittedAt)
  const deadlineMs = submitted.getTime() + _DISPUTE_SLA_DAYS * 24 * 60 * 60 * 1000
  const msLeft = deadlineMs - now
  if (msLeft <= 0) {
    return <span style={{ color: 'var(--color-error)', fontWeight: 600 }}>Overdue</span>
  }
  const hoursLeft = Math.ceil(msLeft / (1000 * 60 * 60))
  const daysLeft = Math.floor(hoursLeft / 24)
  const label = daysLeft > 0 ? `${daysLeft}d ${hoursLeft % 24}h` : `${hoursLeft}h`
  const isUrgent = msLeft < 2 * 24 * 60 * 60 * 1000
  return (
    <span style={isUrgent ? { color: 'var(--color-warning)', fontWeight: 600 } : undefined}>
      {label}
    </span>
  )
}

const STATUS_FILTERS: CBMDisputeStatus[] = [
  'submitted',
  'acknowledged',
  'investigating',
  'escalated_china',
  'resolved_adjusted',
  'resolved_no_change',
  'closed',
]

const STATUS_VARIANT: Record<CBMDisputeStatus, BadgeVariant> = {
  submitted: 'warning',
  acknowledged: 'warning',
  investigating: 'warning',
  escalated_china: 'error',
  resolved_adjusted: 'success',
  resolved_no_change: 'success',
  closed: 'neutral',
}

function statusLabel(status: CBMDisputeStatus): string {
  switch (status) {
    case 'submitted': return 'Submitted'
    case 'acknowledged': return 'Acknowledged'
    case 'investigating': return 'Investigating'
    case 'escalated_china': return 'Escalated to China'
    case 'resolved_adjusted': return 'Resolved — adjusted'
    case 'resolved_no_change': return 'Resolved — no change'
    case 'closed': return 'Closed'
  }
}

export function DisputeList(): JSX.Element {
  const navigate = useNavigate()
  // One clock for the whole table — see useNow. Also makes the countdown tick
  // instead of only refreshing when something unrelated re-renders the list.
  const now = useNow()
  const [statusFilter, setStatusFilter] = useState<CBMDisputeStatus | null>(null)
  const { items: disputes, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount } = useDisputeList(
    statusFilter ? { status: statusFilter } : {},
  )

  useTopBarSlot({ subtitle: 'Customer-filed disputes on cargo measurements.' })

  return (
    <div>

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load disputes">{error.message}</Banner>
        </div>
      )}

      <Card padding={16}>
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>All</Chip>
          {STATUS_FILTERS.map((s) => (
            <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
              {statusLabel(s)}
            </Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding={0}>
          <Table
            columns={[
              { title: 'Billing ID' },
              { title: 'Original CBM', align: 'right' },
              { title: 'Corrected CBM', align: 'right' },
              { title: 'Status' },
              { title: 'Submitted' },
              { title: 'SLA', align: 'right' },
              { title: '', width: '60px' },
            ]}
            rows={disputes.map((d) => ({
              cells: [
                <Mono key="billing">{d.billing_id.slice(0, 8)}…</Mono>,
                <Mono key="orig">{d.original_cbm ?? '—'}</Mono>,
                <Mono key="corrected">{d.corrected_cbm ?? '—'}</Mono>,
                <Badge key="status" variant={STATUS_VARIANT[d.status]}>
                  {statusLabel(d.status)}
                </Badge>,
                <span key="date">{d.submitted_at.slice(0, 10)}</span>,
                <SLACountdown key="sla" submittedAt={d.submitted_at} status={d.status} now={now} />,
                // Disputes are managed inline on BillingDetail — navigate there.
                <ViewLink key="view" onClick={() => navigate(`/billing/${d.billing_id}`)} />,
              ],
            }))}
            loading={loading}
            emptyState={
              !loading && disputes.length === 0 ? (
                <span>✓ No disputes match this filter.</span>
              ) : undefined
            }
          />
        </Card>
        <ListFooter
        shown={disputes.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="disputes"
      />
      </div>
    </div>
  )
}
