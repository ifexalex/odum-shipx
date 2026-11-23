import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { type RefundStatus } from '../../api/refunds'
import { refundTypeLabel } from '../../api/refundsRules'
import { useRefundList } from '../../hooks/useRefunds'
import { Chip, ListFooter, Mono, SearchField, StatusBadge, Table, EmptyState, ErrorState } from '../../design/components'
import { formatDate, formatNgn } from '../../lib/format'
import { statusLabel } from '../../design/status'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

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
  const [search, setSearch] = useState('')
  const { items: refunds, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount, refetch } = useRefundList(
    statusFilter ? { status: statusFilter } : {},
  )

  const filteredRefunds = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return refunds
    return refunds.filter((r) =>
      [r.customer_name, r.invoice_number, r.claim_reference, refundTypeLabel(r.refund_type)]
        .filter(Boolean)
        .some((v) => v!.toLowerCase().includes(q)),
    )
  }, [refunds, search])

  return (
    <ListPage
      header={
        <PageHeader
          title="Refunds"
          meta={'Track refund requests across all customers and containers.'}
        />
      }
      notices={
        <>
          {error && (
            <ErrorState
              compact
              title="Couldn't load refunds"
              error={error}
              onRetry={() => void refetch()}
            />
          )}
        </>
      }
      filters={
        <FilterBar
          label="Filter refunds"
          status={
            <>
              <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
                All
              </Chip>
              {STATUS_FILTERS.map((s) => (
                <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
                  {statusLabel('refund', s)}
                </Chip>
              ))}
            </>
          }
          search={
            <SearchField
              label="Search refunds"
              placeholder="Customer, invoice, claim…"
              value={search}
              onChange={setSearch}
            />
          }
        />
      }
      footer={
        <ListFooter
          shown={filteredRefunds.length}
          total={search.trim() ? filteredRefunds.length : totalCount}
          hasMore={!search.trim() && hasMore}
          loading={isFetchingMore}
          onLoadMore={loadMore}
          noun="refund requests"
          nounOne="refund request"
        />
      }
    >
      <Table
        columns={[
          { title: 'Customer' },
          { title: 'Reference', type: 'reference' },
          { title: 'Type' },
          { title: 'Requested (₦)', type: 'money' },
          { title: 'Approved (₦)', type: 'money' },
          { title: 'Preference' },
          { title: 'Status', type: 'status' },
          { title: 'Requested', type: 'date' },
        ]}
        rows={filteredRefunds.map((r) => ({
          onOpen: () => navigate(`/refunds/${r.id}`, { state: { refund: r } }),
          cells: [
            <span key="customer">{r.customer_name ?? '—'}</span>,
            <Mono key="ref">{r.invoice_number ?? r.claim_reference ?? '—'}</Mono>,
            <span key="type">{refundTypeLabel(r.refund_type)}</span>,
            <Mono key="req">{formatNgn(r.amount_requested_ngn)}</Mono>,
            <Mono key="approved">
              {r.amount_approved_ngn ? formatNgn(r.amount_approved_ngn) : '—'}
            </Mono>,
            <span key="choice">
              {r.customer_choice === 'immediate_refund'
                ? 'Bank refund'
                : r.customer_choice === 'credit_next_shipment'
                  ? 'Credit'
                  : '—'}
            </span>,
            <StatusBadge key="status" kind="refund" status={r.status} />,
            <span key="date">{formatDate(r.created_at)}</span>,
          ],
        }))}
        loading={loading}
        emptyState={
          !loading && filteredRefunds.length === 0 ? (
            <EmptyState compact title="No refund requests match this filter" />
          ) : undefined
        }
      />
    </ListPage>
  )
}
