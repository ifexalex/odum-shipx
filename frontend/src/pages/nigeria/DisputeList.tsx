import type { JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { isTerminalDisputeStatus } from '../../api/billingRules'
import { type CBMDisputeStatus } from '../../api/billing'
import { useSession } from '../../auth/useSession'
import { useDisputeList } from '../../hooks/useBilling'
import { Chip, ListFooter, Mono, StatusBadge, Table, EmptyState, ErrorState } from '../../design/components'
import { useNow } from '../../hooks/useNow'
import styles from './DisputeList.module.css'
import { formatDate } from '../../lib/format'
import { useStatusParam } from '../../lib/useStatusParam'
import { statusLabel } from '../../design/status'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

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

// The values `?status=` may hold (useStatusParam); anything else reads as no filter.
const DISPUTE_STATUSES: readonly CBMDisputeStatus[] = [
  'submitted',
  'acknowledged',
  'investigating',
  'escalated_china',
  'resolved_adjusted',
  'resolved_no_change',
  'closed',
]

export function DisputeList(): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()
  // China staff may not open invoices, so they get the measurement-only dispute screen (UX-01).
  const isChina = session?.role === 'china_office_staff'
  // One clock for the whole table — see useNow. Also makes the countdown tick
  // instead of only refreshing when something unrelated re-renders the list.
  const now = useNow()
  const [statusFilter, setStatusFilter] = useStatusParam<CBMDisputeStatus>(DISPUTE_STATUSES)
  const { items: disputes, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount, refetch } = useDisputeList(
    statusFilter ? { status: statusFilter } : {},
  )

  return (
    <ListPage
      header={
        <PageHeader title="CBM disputes" meta={'Customer-filed disputes on cargo measurements.'} />
      }
      notices={
        <>
          {error && (
            <ErrorState
              compact
              title="Couldn't load disputes"
              error={error}
              onRetry={() => void refetch()}
            />
          )}
        </>
      }
      filters={
        <FilterBar
          label="Filter CBM disputes"
          status={
            <>
              <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
                All
              </Chip>
              {STATUS_FILTERS.map((s) => (
                <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
                  {statusLabel('dispute', s)}
                </Chip>
              ))}
            </>
          }
        />
      }
      footer={
        <ListFooter
          shown={disputes.length}
          total={totalCount}
          hasMore={hasMore}
          loading={isFetchingMore}
          onLoadMore={loadMore}
          noun="disputes"
          nounOne="dispute"
        />
      }
    >
      <Table
        columns={[
          { title: 'Customer' },
          { title: 'Invoice', type: 'reference' },
          { title: 'Container', type: 'reference' },
          { title: 'Original (CBM)', type: 'number' },
          { title: 'Corrected (CBM)', type: 'number' },
          { title: 'Status', type: 'status' },
          { title: 'Submitted', type: 'date' },
          { title: 'SLA', align: 'right' },
        ]}
        rows={disputes.map((d) => ({
          onOpen: () =>
            navigate(isChina ? `/billing/disputes/${d.id}` : `/billing/${d.billing_id}`),
          cells: [
            <span key="customer" className={styles.customer}>
              {d.customer_name ?? '—'}
            </span>,
            <Mono key="invoice">{d.invoice_number ?? '—'}</Mono>,
            <Mono key="container">{d.container_number ?? '—'}</Mono>,
            <Mono key="orig">{d.original_cbm ?? '—'}</Mono>,
            <Mono key="corrected">{d.corrected_cbm ?? '—'}</Mono>,
            <StatusBadge key="status" kind="dispute" status={d.status} />,
            <span key="date">{formatDate(d.submitted_at)}</span>,
            <SLACountdown key="sla" submittedAt={d.submitted_at} status={d.status} now={now} />,
            // Nigeria staff and admins manage a dispute inline on its invoice; China staff cannot open invoices.
          ],
        }))}
        loading={loading}
        emptyState={
          !loading && disputes.length === 0 ? (
            <EmptyState compact title="No disputes match this filter" />
          ) : undefined
        }
      />
    </ListPage>
  )
}
