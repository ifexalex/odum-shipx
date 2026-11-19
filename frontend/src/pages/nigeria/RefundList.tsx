import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { type RefundStatus } from '../../api/refunds'
import { refundTypeLabel } from '../../api/refundsRules'
import { useRefundList } from '../../hooks/useRefunds'
import { Banner, Card, Chip, ListFooter, Mono, StatusBadge, Table, ViewLink } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './RefundList.module.css'
import { formatDate, formatNgn } from '../../lib/format'
import { statusLabel } from '../../design/status'

const STATUS_FILTERS: RefundStatus[] = [
  'pending_review',
  'pending_approval',
  'processed',
  'applied_as_credit',
  'rejected',
]

export function RefundList(): JSX.Element {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<RefundStatus | null>(null)
  const { items: refunds, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount } = useRefundList(
    statusFilter ? { status: statusFilter } : {},
  )

  useTopBarSlot({ subtitle: 'Track refund requests across all customers and containers.' })

  return (
    <div>

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load refunds">{error.message}</Banner>
        </div>
      )}

      <Card padding="default">
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>All</Chip>
          {STATUS_FILTERS.map((s) => (
            <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
              {statusLabel('refund', s)}
            </Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding="none">
          <Table
            columns={[
              { title: 'Type' },
              { title: 'Amount requested (₦)', align: 'right' },
              { title: 'Amount approved (₦)', align: 'right' },
              { title: 'Customer preference' },
              { title: 'Status' },
              { title: 'Requested' },
              { title: '', width: '60px' },
            ]}
            rows={refunds.map((r) => ({
              cells: [
                <span key="type">{refundTypeLabel(r.refund_type)}</span>,
                <Mono key="req">{formatNgn(r.amount_requested_ngn)}</Mono>,
                <Mono key="approved">
                  {r.amount_approved_ngn ? formatNgn(r.amount_approved_ngn) : '—'}
                </Mono>,
                <span key="choice">
                  {r.customer_choice === 'immediate_refund' ? 'Bank refund' :
                   r.customer_choice === 'credit_next_shipment' ? 'Credit' : '—'}
                </span>,
                <StatusBadge key="status" kind="refund" status={r.status} />,
                <span key="date">{formatDate(r.created_at)}</span>,
                <ViewLink key="view" onClick={() => navigate(`/refunds/${r.id}`, { state: { refund: r } })} />,
              ],
            }))}
            loading={loading}
            emptyState={!loading && refunds.length === 0 ? <span>✓ No refund requests match this filter.</span> : undefined}
          />
        </Card>
        <ListFooter
        shown={refunds.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="refund requests"
      />
      </div>
    </div>
  )
}
