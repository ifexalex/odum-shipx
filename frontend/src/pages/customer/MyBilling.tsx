import { type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { type Billing } from '../../api/billing'
import { useBillingList } from '../../hooks/useBilling'
import { Badge, Banner, ListFooter, Mono, type BadgeVariant } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'
import { formatNgn } from '../../lib/format'

const STATUS_VARIANT: Record<Billing['payment_status'], BadgeVariant> = {
  unpaid: 'error',
  partially_paid: 'warning',
  paid: 'success',
  overpaid: 'warning',
  waived: 'neutral',
  released_with_outstanding: 'warning',
  cancelled: 'neutral',
}

function statusLabel(s: Billing['payment_status']): string {
  switch (s) {
    case 'unpaid': return 'Unpaid'
    case 'partially_paid': return 'Partially paid'
    case 'paid': return 'Paid'
    case 'overpaid': return 'Overpaid'
    case 'waived': return 'Waived'
    case 'released_with_outstanding': return 'Released (outstanding)'
    case 'cancelled': return 'Cancelled'
  }
}

export function MyBilling(): JSX.Element {
  const navigate = useNavigate()

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

  return (
    <div className={styles.page}>
      <PageHeader title="My Billing" subtitle="Your payment history and outstanding balances." />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      {loading && <p style={{ color: 'var(--color-ink-4)' }}>Loading…</p>}

      {!loading && records.length === 0 && (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>You're all caught up!</p>
          <p>No billing records yet.</p>
        </div>
      )}

      <div className={styles.cardList}>
        {records.map((b) => {
          const outstanding = Number(b.outstanding_ngn)
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
                <p className={styles.cardTitle}>{b.container_number ?? b.container_id}</p>
                <div className={styles.cardMeta}>
                  <span>Total due: <Mono>{formatNgn(b.total_due_ngn)}</Mono></span>
                  <span>Paid: <Mono>{formatNgn(b.total_paid_ngn)}</Mono></span>
                </div>
              </div>
              <div className={styles.cardRight}>
                <Badge variant={STATUS_VARIANT[b.payment_status]}>{statusLabel(b.payment_status)}</Badge>
                {outstanding > 0 && (
                  <span className={styles.amountSub} style={{ color: 'var(--color-error)' }}>
                    {formatNgn(outstanding)} outstanding
                  </span>
                )}
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
      />
    </div>
  )
}
