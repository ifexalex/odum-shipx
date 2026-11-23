import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { billingApi, type Billing, type PaymentStatus } from '../../api/billing'
import { canGenerateInvoices } from '../../api/billingRules'
import { billingKeys } from '../../api/keys'
import { formatNgnCompact, formatDate, formatNgn } from '../../lib/format'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Banner, Button, Chip, DateRangeFilter, ExportButton, Icon, ListFooter, Mono, StatCard, StatusBadge, Table, UserCell, Pressable, SearchField, EmptyState, ErrorState } from '../../design/components'
import { useSession } from '../../auth/useSession'
import { useBillingList } from '../../hooks/useBilling'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { useListExport } from '../../hooks/useListExport'
import { type SortableColumn, useTableSort } from '../../hooks/useTableSort'
import { GenerateBillingModal } from './GenerateBillingModal'
import { BillingSubNav } from './BillingSubNav'
import styles from './BillingList.module.css'
import { statusLabel } from '../../design/status'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage, StatRow } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

// 'Reference' (invoice_number, text) defaults asc; 'Billed' (billed_at,
// "when this record was billed") defaults desc — same created/billed-desc,
// text-asc convention followed by ContainerList and ClaimList.
const SORT_COLUMNS: SortableColumn[] = [
  { index: 0, field: 'invoice_number', defaultDirection: 'asc' },
  { index: 6, field: 'billed_at', defaultDirection: 'desc' },
]

// The statuses an invoice list filters on, in its own words from the status registry (FD-08).
const STATUS_FILTERS: Array<{ key: PaymentStatus; label: string }> = (
  ['unpaid', 'partially_paid', 'paid', 'overpaid', 'waived', 'released_with_outstanding', 'cancelled'] as const
).map((key) => ({ key, label: statusLabel('invoice', key) }))

// Money still owed on an invoice: what the "Outstanding" stat opens.
const OWED: PaymentStatus[] = ['unpaid', 'partially_paid', 'released_with_outstanding']

function fmtNgn(val: string | number | null | undefined): string {
  if (val == null) return '—'
  const n = Number(val)
  if (n === 0) return '—'
  return formatNgn(n)
}

type OpenModalTarget = 'payment' | 'release'

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
function rowAction(b: Billing, openBilling: (b: Billing, modal?: OpenModalTarget) => void): JSX.Element | null {
  if (b.payment_status === 'unpaid' || b.payment_status === 'partially_paid') {
    return (
      <Button variant="secondary" size="sm" icon="coin" mutates={false}
        onClick={(e) => { e.stopPropagation(); openBilling(b, 'payment') }}>
        Record payment
      </Button>
    )
  }
  if (b.payment_status === 'paid') {
    return (
      <Button variant="secondary" size="sm" icon="card" mutates={false}
        onClick={(e) => { e.stopPropagation(); openBilling(b, 'release') }}>
        Release
      </Button>
    )
  }
  return null
}

export function BillingList(): JSX.Element {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // Carries the record in router state so BillingDetail does not fall back to
  // its paginated list-scan — see rowAction above.
  const openBilling = (b: Billing, openModal?: OpenModalTarget): void => {
    void navigate(`/billing/${b.id}`, { state: { billing: b, ...(openModal ? { openModal } : {}) } })
  }
  const { session } = useSession()
  // Single-select via the top chips; the Filters panel below offers a
  // granular multi-select over the same state (same idiom as
  // china/ContainerList.tsx's activeStatuses — one value can't silently AND
  // with several from the other entry point since they share this array).
  const [activeStatuses, setActiveStatuses] = useState<PaymentStatus[] | null>(null)
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '')
  // Opt-in "billed within" filter, preset + exact custom range — null/''
  // means no date filter. Must stay that way by default: a "helpful" default
  // scope would silently hide most of a tenant's billing records, same
  // rationale as ContainerList's date filter.
  const billedRange = useDateRangeFilter()
  const [overdueOnly, setOverdueOnly] = useState(false)

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
    ...(overdueOnly ? { overdue: true } : {}),
    ...(sortField ? { sort: sortField, direction: sortDirection } : {}),
  }
  const exportList = useListExport((format: 'xlsx' | 'csv') => billingApi.exportList(listParams, format))

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

  function clearAllFilters(): void {
    setActiveStatuses(null)
    setSearch('')
    setOverdueOnly(false)
    billedRange.clear()
  }

  // A stat applies its filter, or lifts it when it is already the one applied (FD-18).
  const sameStatuses = (statuses: PaymentStatus[]): boolean => activeStatuses?.join() === statuses.join()
  function selectStatuses(statuses: PaymentStatus[]): void {
    setOverdueOnly(false)
    setActiveStatuses(sameStatuses(statuses) ? null : statuses)
  }
  function clearStatus(): void {
    setOverdueOnly(false)
    setActiveStatuses(null)
  }
  function selectOverdue(): void {
    setActiveStatuses(null)
    setOverdueOnly((on) => !on)
  }
  const activeFilters = (activeStatuses ? 1 : 0) + (overdueOnly ? 1 : 0) + (billedRange.isActive ? 1 : 0)

  return (
    <ListPage
      header={
        <PageHeader
          title="Billing"
          primary={
            canGenerate && (
              <Button variant="primary" icon="plus" onClick={() => setGenerateOpen(true)}>
                Generate billing
              </Button>
            )
          }
          actions={
            isAdmin && <ExportButton formats={['xlsx', 'csv']} onExport={exportList.onExport} />
          }
        />
      }
      tabs={<BillingSubNav active="invoices" />}
      notices={
        <>
          {error && (
            <ErrorState
              compact
              title="Couldn't load billing"
              error={error}
              onRetry={() => void refetch()}
            />
          )}
          {exportList.error && (
            <Banner
              variant="error"
              title="Couldn't export invoices"
              dismissible
              onDismiss={exportList.dismissError}
            >
              {exportList.error}
            </Banner>
          )}
        </>
      }
      // Four numbers to act on, each a filter (FD-18). "Paid this month" was history and "Total records" filler.
      stats={
        <StatRow>
          <StatCard
            label="Outstanding"
            value={formatNgnCompact(stats?.outstanding_ngn)}
            sublabel="still owed"
            icon="warn"
            selected={sameStatuses(OWED)}
            onSelect={() => selectStatuses(OWED)}
          />
          <StatCard
            label="Overdue (30+ days)"
            value={stats?.overdue ?? 0}
            sublabel="owed for over a month"
            icon="clock"
            selected={overdueOnly}
            onSelect={selectOverdue}
          />
          <StatCard
            label={statusLabel('invoice', 'unpaid')}
            value={stats?.unpaid ?? 0}
            sublabel="nothing paid yet"
            icon="coin"
            selected={sameStatuses(['unpaid'])}
            onSelect={() => selectStatuses(['unpaid'])}
          />
          <StatCard
            label={statusLabel('invoice', 'partially_paid')}
            value={stats?.partially_paid ?? 0}
            sublabel="part of it paid"
            icon="card"
            selected={sameStatuses(['partially_paid'])}
            onSelect={() => selectStatuses(['partially_paid'])}
          />
        </StatRow>
      }
      filters={
        <FilterBar
          label="Filter invoices"
          status={
            <>
              <Chip active={activeStatuses === null && !overdueOnly} onClick={clearStatus}>
                All{stats && <span className={styles.chipCount}>{stats.total}</span>}
              </Chip>
              {STATUS_FILTERS.map(({ key, label }) => (
                <Chip key={key} active={sameStatuses([key])} onClick={() => selectStatuses([key])}>
                  {label}
                  {stats && key in stats && (
                    <span className={styles.chipCount}>
                      {Number(stats[key as keyof typeof stats] ?? 0)}
                    </span>
                  )}
                </Chip>
              ))}
            </>
          }
          search={
            <SearchField
              label="Search invoices"
              placeholder="Reference, customer, container…"
              value={search}
              onChange={setSearch}
            />
          }
          dateRange={<DateRangeFilter label="Billed" range={billedRange} />}
          more={
            <>
              {/* Granular multi-select across all statuses — independent
                entry point from the single-select chips above, same
                underlying activeStatuses state (see toggleStatus). */}
              <div className={styles.filtersPanelLabel}>Any status</div>
              <div className={styles.filtersPanelScroll}>
                {STATUS_FILTERS.map(({ key, label }) => {
                  const isChecked = activeStatuses?.includes(key) ?? false
                  return (
                    <Pressable
                      key={key}
                      type="button"
                      role="checkbox"
                      aria-checked={isChecked}
                      className={[
                        styles.filtersPanelItem,
                        isChecked ? styles.filtersPanelItemActive : '',
                      ].join(' ')}
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
            </>
          }
          activeCount={activeFilters}
          onClear={clearAllFilters}
        />
      }
      footer={
        <ListFooter
          shown={records.length}
          total={totalCount}
          hasMore={hasMore}
          loading={isFetchingMore}
          onLoadMore={loadMore}
          noun="billing records"
          nounOne="billing record"
        />
      }
    >
      <Table
        cardBreakpoint={860}
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
            <Mono key="ref" color="var(--color-ink)">
              {b.invoice_number ?? '—'}
            </Mono>,
            b.customer_name ? (
              <UserCell key="cust" name={b.customer_name} email="" />
            ) : (
              <span key="cust" style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-sm)' }}>
                —
              </span>
            ),
            <Mono key="ctn">{b.container_number ?? '—'}</Mono>,
            <Mono key="total">{fmtNgn(b.total_due_ngn)}</Mono>,
            <Mono
              key="out"
              color={
                Number(b.outstanding_ngn) > 0
                  ? 'var(--color-error)'
                  : Number(b.outstanding_ngn) < 0
                    ? 'var(--color-info)'
                    : 'var(--color-success)'
              }
            >
              {fmtNgn(b.outstanding_ngn)}
            </Mono>,
            <StatusBadge key="status" kind="invoice" status={b.payment_status} />,
            <span key="billed" className={styles.metaText}>
              {b.billed_at ? formatDate(b.billed_at, 'short') : '—'}
            </span>,
            <div key="action" className={styles.rowActions}>
              {rowAction(b, openBilling)}
            </div>,
          ],
        }))}
        loading={isLoading}
        emptyState={
          !isLoading && records.length === 0 ? (
            <EmptyState compact title="No billing records match this filter" />
          ) : undefined
        }
        sort={sort}
        onSort={onSort}
      />
      {generateOpen && <GenerateBillingModal onClose={() => setGenerateOpen(false)} />}
    </ListPage>
  )
}
