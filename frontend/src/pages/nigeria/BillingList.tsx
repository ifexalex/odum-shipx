import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { billingApi, type Billing, type PaymentStatus } from '../../api/billing'
import { canGenerateInvoices } from '../../api/billingRules'
import { billingKeys } from '../../api/keys'
import { formatNgnCompact, formatDate, formatNgn } from '../../lib/format'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Banner, Button, Card, Chip, DateRangeFilter, ExportButton, Icon, ListFooter, Mono, StatCard, StatusBadge, Table, UserCell, Pressable, SearchField, EmptyState, ErrorState } from '../../design/components'
import { useSession } from '../../auth/useSession'
import { useBillingList } from '../../hooks/useBilling'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { useListExport } from '../../hooks/useListExport'
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

function fmtNgn(val: string | number | null | undefined): string {
  if (val == null) return '—'
  const n = Number(val)
  if (n === 0) return '—'
  return formatNgn(n)
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
/** The row's next step, or nothing: opening the row itself is how you view a record (FD-13). */
function rowAction(b: Billing, openBilling: (b: Billing) => void): JSX.Element | null {
  if (b.payment_status === 'unpaid' || b.payment_status === 'partially_paid') {
    return (
      <Button variant="secondary" size="sm" icon="coin" mutates={false}
        onClick={(e) => { e.stopPropagation(); openBilling(b) }}>
        Record payment
      </Button>
    )
  }
  if (b.payment_status === 'paid') {
    return (
      <Button variant="secondary" size="sm" icon="card" mutates={false}
        onClick={(e) => { e.stopPropagation(); openBilling(b) }}>
        Release
      </Button>
    )
  }
  return null
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

  const { sort, onSort, sortField, sortDirection } = useTableSort(SORT_COLUMNS)

  // What the list is showing: the same object drives the query below and the Export button, so an export is the
  // rows on screen (every page of them), not a second reading of the filters.
  const listParams = {
    ...(activeStatuses?.length ? { status: activeStatuses.join(',') } : {}),
    ...(search ? { q: search } : {}),
    ...(billedRange.createdAfter ? { created_after: billedRange.createdAfter } : {}),
    ...(billedRange.createdBefore ? { created_before: billedRange.createdBefore } : {}),
    ...(sortField ? { sort: sortField, direction: sortDirection } : {}),
  }
  const exportList = useListExport((format: 'xlsx' | 'csv') => billingApi.exportList(listParams, format))

  useTopBarSlot({
    actions:
      isAdmin || canGenerate ? (
        <>
          {isAdmin && <ExportButton formats={['xlsx', 'csv']} onExport={exportList.onExport} />}
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

  const { items: records, isLoading, error, hasMore, loadMore, isFetchingMore, totalCount, refetch } = useBillingList(listParams)

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
          <ErrorState compact title="Couldn't load billing" error={error} onRetry={() => void refetch()} />
        </div>
      )}
      {exportList.error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't export invoices" dismissible onDismiss={exportList.dismissError}>
            {exportList.error}
          </Banner>
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
      <Card padding="default" style={{ marginBottom: 'var(--space-4)' }}>
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
          <SearchField label="Search invoices" placeholder="Reference, customer, container…" value={search} onChange={setSearch} />
          <DateRangeFilter label="Billed" range={billedRange} />
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
                        <Pressable
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
                        </Pressable>
                      )
                    })}
                  </div>

                  <Button variant="ghost" size="sm" onClick={clearAllFilters}>
                    Clear all filters
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      </Card>

      {/* Table */}
      <Card padding="none">
        <Table
          cardBreakpoint={960}
          columns={[
            { title: 'Reference', type: 'reference', sortable: true },
            { title: 'Customer' },
            { title: 'Container', type: 'reference' },
            { title: 'Total (₦)', type: 'money' },
            { title: 'Outstanding (₦)', type: 'money' },
            { title: 'Status', type: 'status' },
            { title: 'Billed', type: 'date', sortable: true },
            { title: '', type: 'action', width: '140px' },
          ]}
          rows={records.map((b) => ({
            onOpen: () => openBilling(b),
            openLabel: `Open invoice ${b.invoice_number ?? ''}`.trim(),
            cells: [
              <Mono key="ref" color="var(--color-ink)">{b.invoice_number ?? '—'}</Mono>,
              b.customer_name
                ? <UserCell key="cust" name={b.customer_name} email="" />
                : <span key="cust" style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-sm)' }}>—</span>,
              <Mono key="ctn">{b.container_number ?? '—'}</Mono>,
              <Mono key="total">{fmtNgn(b.total_due_ngn)}</Mono>,
              <Mono key="out" color={Number(b.outstanding_ngn) > 0 ? 'var(--color-error)' : Number(b.outstanding_ngn) < 0 ? 'var(--color-info)' : 'var(--color-success)'}>
                {fmtNgn(b.outstanding_ngn)}
              </Mono>,
              <StatusBadge key="status" kind="invoice" status={b.payment_status} />,
              <span key="billed" className={styles.metaText}>
                {b.billed_at
                  ? formatDate(b.billed_at, 'short')
                  : '—'}
              </span>,
              <div key="action" className={styles.rowActions}>
                {rowAction(b, openBilling)}
              </div>,
            ],
          }))}
          loading={isLoading}
          emptyState={!isLoading && records.length === 0 ? <EmptyState compact title="No billing records match this filter" /> : undefined}
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
        nounOne="billing record"
      />

      {generateOpen && <GenerateBillingModal onClose={() => setGenerateOpen(false)} />}
    </div>
  )
}
