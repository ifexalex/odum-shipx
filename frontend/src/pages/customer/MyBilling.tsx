import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { useBillingList } from '../../hooks/useBilling'
import { Banner, Card, Chip, EmptyState, Icon, ListFooter, Mono, StatCard, StatusBadge, LinesSkeleton } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'
import { formatDate, formatNgn, formatNgnCompact } from '../../lib/format'

type BillingFilter = 'all' | 'unpaid' | 'settled'

export function MyBilling(): JSX.Element {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<BillingFilter>('all')

  // `useBillingList` is the same paginated hook the staff BillingList uses — the
  // backend force-scopes GET /v1/billing to the caller's own customer_id for the
  // customer role, so no client-side filter is needed or trusted here.
  const {
    items: records,
    isLoading: loading,
    error: loadError,
    hasMore,
    loadMore,
    isFetchingMore,
    totalCount,
  } = useBillingList()

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load billing records.'
    : null

  const { totalDue, totalPaid, totalBalance, unpaidCount, settledCount } = useMemo(() => {
    let due = 0
    let paid = 0
    let balance = 0
    let unpaid = 0
    let settled = 0
    for (const b of records) {
      const out = Number(b.outstanding_ngn ?? 0)
      due += Number(b.total_due_ngn ?? 0)
      paid += Number(b.total_paid_ngn ?? 0)
      balance += out
      if (out > 0) unpaid += 1
      else settled += 1
    }
    return { totalDue: due, totalPaid: paid, totalBalance: balance, unpaidCount: unpaid, settledCount: settled }
  }, [records])

  const visibleRecords = useMemo(() => {
    if (filter === 'unpaid') return records.filter((b) => Number(b.outstanding_ngn ?? 0) > 0)
    if (filter === 'settled') return records.filter((b) => Number(b.outstanding_ngn ?? 0) <= 0)
    return records
  }, [records, filter])

  return (
    <div className={styles.page}>
      <PageHeader title="My billing" meta="Your payment history and outstanding balances." />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      {loading && <LinesSkeleton label="Loading" />}

      {!loading && records.length === 0 && (
        <Card padding="default">
          <EmptyState icon="coin" title="You're all caught up!" body="No billing records yet." />
        </Card>
      )}

      {!loading && records.length > 0 && (
        <>
          <div className={styles.statsRow}>
            <StatCard
              label="Total billed"
              value={formatNgnCompact(totalDue)}
              icon="file"
              sublabel={`${records.length} ${records.length === 1 ? 'invoice' : 'invoices'}`}
            />
            <StatCard
              label="Total paid"
              value={formatNgnCompact(totalPaid)}
              icon="check"
              sublabel="confirmed payments"
            />
            <StatCard
              label="Balance due"
              value={totalBalance > 0 ? formatNgnCompact(totalBalance) : '₦0'}
              icon="coin"
              accentColor={totalBalance > 0 ? 'var(--color-error)' : undefined}
              sublabel={totalBalance > 0 ? `${unpaidCount} awaiting payment` : 'all settled'}
            />
          </div>

          <div className={styles.filterRow} role="group" aria-label="Filter invoices">
            <Chip active={filter === 'all'} count={records.length} onClick={() => setFilter('all')}>
              All
            </Chip>
            <Chip active={filter === 'unpaid'} count={unpaidCount} onClick={() => setFilter('unpaid')}>
              Unpaid
            </Chip>
            <Chip active={filter === 'settled'} count={settledCount} onClick={() => setFilter('settled')}>
              Settled
            </Chip>
          </div>
        </>
      )}

      {!loading && records.length > 0 && visibleRecords.length === 0 && (
        <Card padding="default">
          <EmptyState
            compact
            icon="coin"
            title="No matching invoices"
            body="Try switching the filter above to see your other billing records."
            onClearFilters={() => setFilter('all')}
          />
        </Card>
      )}

      <div className={styles.cardList}>
        {visibleRecords.map((b) => {
          const due = Number(b.total_due_ngn ?? 0)
          const paid = Number(b.total_paid_ngn ?? 0)
          const outstanding = Number(b.outstanding_ngn ?? 0)
          const paidPct = due > 0 ? Math.min(100, Math.round((paid / due) * 100)) : 100
          const showBar = due > 0 && outstanding > 0 && paid > 0
          return (
            <div
              key={b.id}
              className={styles.card}
              onClick={() => navigate(`/my-billing/${b.id}`, { state: { billing: b } })}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && navigate(`/my-billing/${b.id}`, { state: { billing: b } })}
            >
              <div className={styles.cardLeft}>
                <p className={styles.cardTitle}>{b.container_number ?? b.invoice_number ?? 'Invoice'}</p>
                <div className={styles.cardMeta}>
                  {b.invoice_number && b.container_number && <span>Ref <Mono>{b.invoice_number}</Mono></span>}
                  {b.billed_at && <span>Billed {formatDate(b.billed_at)}</span>}
                  <span>Total due: <Mono>{formatNgn(b.total_due_ngn)}</Mono></span>
                  <span>Paid: <Mono>{formatNgn(b.total_paid_ngn)}</Mono></span>
                </div>
                {showBar && (
                  <div className={styles.progressWrap}>
                    <div className={styles.progressHead}>
                      <span>Payment progress</span>
                      <span>{paidPct}% paid</span>
                    </div>
                    <div className={styles.progressTrack}>
                      <div className={styles.progressFill} style={{ width: `${paidPct}%` }} />
                    </div>
                  </div>
                )}
              </div>
              <div className={styles.cardTrailing}>
                <div className={styles.cardRight}>
                  <StatusBadge kind="invoice" status={b.payment_status} audience="customer" />
                  {outstanding > 0 && (
                    <span className={styles.amountSub} style={{ color: 'var(--color-error)' }}>
                      {formatNgn(outstanding)} outstanding
                    </span>
                  )}
                </div>
                <Icon name="chevright" size={16} color="var(--color-ink-4)" />
              </div>
            </div>
          )
        })}
      </div>

      <ListFooter
        shown={records.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="billing records"
        nounOne="billing record"
      />
    </div>
  )
}
