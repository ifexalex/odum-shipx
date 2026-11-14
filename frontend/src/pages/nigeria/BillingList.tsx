import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { billingApi, type Billing, type PaymentStatus } from '../../api/billing'
import { canGenerateInvoices } from '../../api/billingRules'
import { billingKeys } from '../../api/keys'
import { formatNgnCompact } from '../../lib/format'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Badge, Banner, Button, Card, Chip, DateRangeFilter, Icon, ListFooter, Mono, StatCard, Table, UserCell, type BadgeVariant } from '../../design/components'
import { useSession } from '../../auth/useSession'
import { useBillingList } from '../../hooks/useBilling'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { type SortableColumn, useTableSort } from '../../hooks/useTableSort'
import { useTopBarSlot } from '../../shell/TopBarContext'
import { GenerateBillingModal } from './GenerateBillingModal'
import styles from './BillingList.module.css'

// 'Reference' (invoice_number, text) defaults asc; 'Billed' (billed_at,
// "when this record was billed") defaults desc — same created/billed-desc,
// text-asc convention followed by ContainerList and ClaimList.
const SORT_COLUMNS: SortableColumn[] = [
  { index: 0, field: 'invoice_number', defaultDirection: 'asc' },
  { index: 6, field: 'billed_at', defaultDirection: 'desc' },
]

const STATUS_FILTERS: Array<{ key: PaymentStatus; label: string }> = [
  { key: 'unpaid',                   label: 'Unpaid' },
  { key: 'partially_paid',           label: 'Partial' },
  { key: 'paid',                     label: 'Paid' },
  { key: 'overpaid',                 label: 'Overpaid' },
  { key: 'waived',                   label: 'Waived' },
  { key: 'released_with_outstanding', label: 'Released w/ outstanding' },
]

const STATUS_VARIANT: Record<PaymentStatus, BadgeVariant> = {
  unpaid:                    'error',
  partially_paid:            'warning',
  paid:                      'success',
  overpaid:                  'info',
  waived:                    'neutral',
  released_with_outstanding: 'warning',
  cancelled:                 'neutral',
}

const STATUS_LABEL: Record<PaymentStatus, string> = {
  unpaid:                    'Unpaid',
  partially_paid:            'Partial',
  paid:                      'Paid',
  overpaid:                  'Overpaid',
  waived:                    'Waived',
  released_with_outstanding: 'Released',
  cancelled:                 'Cancelled',
}

function fmtNgn(val: string | number | null | undefined): string {
  if (val == null) return '—'
  const n = Number(val)
  if (n === 0) return '—'
  return `₦${n.toLocaleString('en-NG', { maximumFractionDigits: 0 })}`
}

// `openBilling` must carry the record in router state. BillingDetail reads
// `location.state.billing` and only falls back to load() otherwise — and that
// fallback fetches the FIRST PAGE of the billing list and searches it by id
// client-side, because the API has no GET /v1/billing/{billing-id}. With the
// default page size of 20 (shared/pagination.py), any older billing opened
// without state renders "Billing record not found."
//
// AdminCustomerDetail already passes state when opening a billing; this list
// was the outlier that did not.
function rowAction(b: Billing, openBilling: (b: Billing) => void): JSX.Element {
  if (b.payment_status === 'unpaid' || b.payment_status === 'partially_paid') {
    return (
      <Button variant="accent" size="sm" icon="coin"
        onClick={(e) => { e.stopPropagation(); openBilling(b) }}>
        Record payment
      </Button>
    )
  }
  if (b.payment_status === 'paid') {
    return (
      <Button variant="secondary" size="sm" icon="card"
        onClick={(e) => { e.stopPropagation(); openBilling(b) }}>
        Release
      </Button>
    )
  }
  return (
    <Button variant="ghost" size="sm"
      onClick={(e) => { e.stopPropagation(); openBilling(b) }}>
      View
    </Button>
  )
}

export function BillingList(): JSX.Element {
  const navigate = useNavigate()
  // Carries the record in router state so BillingDetail does not fall back to
  // its paginated list-scan — see rowAction above.
  const openBilling = (b: Billing): void => {
    void navigate(`/billing/${b.id}`, { state: { billing: b } })
  }
  const { session } = useSession()
  // Single-select via the top chips; the Filters panel below offers a
  // granular multi-select over the same state (same idiom as
  // china/ContainerList.tsx's activeStatuses — one value can't silently AND
  // with several from the other entry point since they share this array).
  const [activeStatuses, setActiveStatuses] = useState<PaymentStatus[] | null>(null)
  const [search, setSearch] = useState('')
  // Opt-in "billed within" filter, preset + exact custom range — null/''
  // means no date filter. Must stay that way by default: a "helpful" default
  // scope would silently hide most of a tenant's billing records, same
  // rationale as ContainerList's date filter.
  const billedRange = useDateRangeFilter()
  const [filtersOpen, setFiltersOpen] = useState(false)

  const isAdmin = session?.role === 'tenant_admin'
  const canGenerate = session ? canGenerateInvoices(session.role) : false
  const [generateOpen, setGenerateOpen] = useState(false)

  useTopBarSlot({
    actions:
      isAdmin || canGenerate ? (
        <>
          {isAdmin && <Button variant="secondary" icon="download">Export</Button>}
          {canGenerate && (
            <Button variant="primary" icon="plus" onClick={() => setGenerateOpen(true)}>Generate billing</Button>
          )}
        </>
      ) : null,
  })

  // Tenant-wide aggregates for the stats row + status chips — SQL-computed
  // server-side (GET /v1/billing/stats) so the figures stay correct as billing
  // grows to tens of thousands, instead of summing a capped fetched sample.
  const { data: stats } = useQuery({
    queryKey: billingKeys.stats(),
    queryFn: () => billingApi.stats(),
    staleTime: STALE_5_MIN,
  })

  const { sort, onSort, sortField, sortDirection } = useTableSort(SORT_COLUMNS)

  const { items: records, isLoading, error, hasMore, loadMore, isFetchingMore, totalCount } = useBillingList({
    ...(activeStatuses?.length ? { status: activeStatuses.join(',') } : {}),
    ...(search ? { q: search } : {}),
    ...(billedRange.createdAfter ? { created_after: billedRange.createdAfter } : {}),
    ...(billedRange.createdBefore ? { created_before: billedRange.createdBefore } : {}),
    ...(sortField ? { sort: sortField, direction: sortDirection } : {}),
  })

  // Toggling a single status here overwrites `activeStatuses` — matches the
  // top chips' single-select semantics rather than adding a second,
  // independently-toggleable multi-select that could silently combine with
  // whichever chip is highlighted.
  function toggleStatus(status: PaymentStatus): void {
    const current = activeStatuses ?? []
    const next = current.includes(status) ? current.filter((s) => s !== status) : [...current, status]
    setActiveStatuses(next.length ? next : null)
  }

  // Note: does NOT reset the "Billed" date range — same convention as
  // china/ContainerList.tsx's standalone date-created control, which lives
  // outside the Filters panel and isn't touched by the panel's own Clear.
  function clearAllFilters(): void {
    setActiveStatuses(null)
    setSearch('')
    setFiltersOpen(false)
  }

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load billing">{error.message}</Banner>
        </div>
      )}

      {/* Stats row */}
      <div className={styles.statsRow}>
        <StatCard label="Outstanding" value={formatNgnCompact(stats?.outstanding_ngn)} sublabel="unpaid + partial" icon="warn" />
        <StatCard label="Paid this month" value={formatNgnCompact(stats?.paid_this_month_ngn)} sublabel="confirmed payments" icon="check" />
        <StatCard label="Overdue (30+ days)" value={stats?.overdue ?? 0} sublabel="records flagged" icon="clock" />
        <StatCard label="Total records" value={stats?.total ?? 0} sublabel="all time" icon="coin" />
      </div>

      {/* Filter bar */}
      <Card padding={16} style={{ marginBottom: 16 }}>
        <div className={styles.filterRow}>
          <div className={styles.chips}>
            <Chip active={activeStatuses === null} onClick={() => setActiveStatuses(null)}>
              All{stats && <span className={styles.chipCount}>{stats.total}</span>}
            </Chip>
            {STATUS_FILTERS.map(({ key, label }) => (
              <Chip
                key={key}
                active={activeStatuses?.join() === key}
                onClick={() => setActiveStatuses([key])}
              >
                {label}
                {stats && (
                  <span className={styles.chipCount}>{Number(stats[key as keyof typeof stats] ?? 0)}</span>
                )}
              </Chip>
            ))}
          </div>
          <div className={styles.searchWrap}>
            <Icon name="search" size={14} color="var(--color-ink-4)" />
            <input
              className={styles.searchInput}
              placeholder="Reference, customer, container…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <DateRangeFilter value={billedRange.daysBack} onChange={billedRange.handlePreset} />
          <div className={styles.customDateWrap}>
            <label htmlFor="billing_billed_from" className={styles.customDateLabel}>From</label>
            <input
              id="billing_billed_from"
              type="date"
              className={styles.customDateInput}
              value={billedRange.dateFrom}
              max={billedRange.dateTo || undefined}
              onChange={(e) => billedRange.handleCustomFrom(e.target.value)}
            />
            <label htmlFor="billing_billed_to" className={styles.customDateLabel}>To</label>
            <input
              id="billing_billed_to"
              type="date"
              className={styles.customDateInput}
              value={billedRange.dateTo}
              min={billedRange.dateFrom || undefined}
              onChange={(e) => billedRange.handleCustomTo(e.target.value)}
            />
          </div>
          <div className={styles.filtersWrap}>
            <Button variant="secondary" icon="filter" onClick={() => setFiltersOpen((o) => !o)}>
              Filters
            </Button>
            {filtersOpen && (
              <>
                <div className={styles.filtersOverlay} onClick={() => setFiltersOpen(false)} />
                <div className={styles.filtersPanel} role="dialog" aria-label="Filters">
                  <div className={styles.filtersPanelHeader}>Filters</div>

                  {/* Granular multi-select across all statuses — independent
                      entry point from the single-select chips above, same
                      underlying activeStatuses state (see toggleStatus). */}
                  <div className={styles.filtersPanelLabel}>Status</div>
                  <div className={styles.filtersPanelScroll}>
                    {STATUS_FILTERS.map(({ key, label }) => {
                      const isChecked = activeStatuses?.includes(key) ?? false
                      return (
                        <button
                          key={key}
                          type="button"
                          role="checkbox"
                          aria-checked={isChecked}
                          className={[styles.filtersPanelItem, isChecked ? styles.filtersPanelItemActive : ''].join(' ')}
                          onClick={() => toggleStatus(key)}
                        >
                          <span className={styles.checkSlot}>
                            {isChecked && <Icon name="check" size={13} color="var(--color-primary)" />}
                          </span>
                          {label}
                        </button>
                      )
                    })}
                  </div>

                  <button type="button" className={styles.filtersPanelClear} onClick={clearAllFilters}>
                    Clear all filters
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </Card>

      {/* Record count */}
      <div className={styles.activeFilters}>
        <span className={styles.recordCount}>
          Showing <strong style={{ color: 'var(--color-ink)' }}>{records.length}</strong> records
        </span>
      </div>

      {/* Table */}
      <Card padding={0}>
        <Table
          cardBreakpoint={960}
          columns={[
            { title: 'Reference', sortable: true },
            { title: 'Customer' },
            { title: 'Container' },
            { title: 'Total (₦)', align: 'right' },
            { title: 'Outstanding (₦)', align: 'right' },
            { title: 'Status' },
            { title: 'Billed', sortable: true },
            { title: '', width: '140px' },
          ]}
          rows={records.map((b) => ({
            cells: [
              <Mono key="ref" color="var(--color-ink)">{b.invoice_number ?? '—'}</Mono>,
              b.customer_name
                ? <UserCell key="cust" name={b.customer_name} email="" />
                : <span key="cust" style={{ color: 'var(--color-ink-4)', fontSize: 13 }}>—</span>,
              <Mono key="ctn">{b.container_number ?? '—'}</Mono>,
              <Mono key="total">{fmtNgn(b.total_due_ngn)}</Mono>,
              <Mono key="out" color={Number(b.outstanding_ngn) > 0 ? 'var(--color-error)' : Number(b.outstanding_ngn) < 0 ? 'var(--color-info)' : 'var(--color-success)'}>
                {fmtNgn(b.outstanding_ngn)}
              </Mono>,
              <Badge key="status" variant={STATUS_VARIANT[b.payment_status]}>
                {STATUS_LABEL[b.payment_status]}
              </Badge>,
              <span key="billed" className={styles.metaText}>
                {b.billed_at
                  ? new Date(b.billed_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
                  : '—'}
              </span>,
              <div key="action" className={styles.rowActions}>
                {rowAction(b, openBilling)}
              </div>,
            ],
          }))}
          loading={isLoading}
          emptyState={!isLoading && records.length === 0 ? <span>No billing records match this filter.</span> : undefined}
          sort={sort}
          onSort={onSort}
        />
      </Card>

      <ListFooter
        shown={records.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="billing records"
      />

      {generateOpen && <GenerateBillingModal onClose={() => setGenerateOpen(false)} />}
    </div>
  )
}
