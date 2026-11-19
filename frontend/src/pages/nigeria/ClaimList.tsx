import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { claimsApi, type Claim, type DamageClaimStatus } from '../../api/claims'
import { claimKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Badge, Banner, Button, Card, Chip, DateRangeFilter, Icon, Mono, StatCard, Table, UserCell, ListFooter, type BadgeVariant } from '../../design/components'
import { useSession } from '../../auth/useSession'
import { useClaimList } from '../../hooks/useClaims'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { type SortableColumn, useTableSort } from '../../hooks/useTableSort'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './ClaimList.module.css'
import { formatDate } from '../../lib/format'

// 'Claim ID' (reference, text) defaults asc; 'Filed' (created_at) defaults
// desc (newest first) — same convention as BillingList/ContainerList.
const SORT_COLUMNS: SortableColumn[] = [
  { index: 0, field: 'reference', defaultDirection: 'asc' },
  { index: 7, field: 'created_at', defaultDirection: 'desc' },
]

const STATUS_FILTERS: Array<{ key: DamageClaimStatus; label: string }> = [
  { key: 'filed',              label: 'Filed' },
  { key: 'under_inspection',   label: 'Under inspection' },
  { key: 'pending_resolution', label: 'Pending resolution' },
  { key: 'resolved',           label: 'Resolved' },
  { key: 'closed',             label: 'Closed' },
]

const STATUS_VARIANT: Record<DamageClaimStatus, BadgeVariant> = {
  filed:                'error',
  under_inspection:     'warning',
  inspection_complete:  'warning',
  pending_resolution:   'info',
  resolved:             'success',
  closed:               'neutral',
}

const STATUS_LABEL: Record<DamageClaimStatus, string> = {
  filed:                'Filed',
  under_inspection:     'Under inspection',
  inspection_complete:  'Inspection complete',
  pending_resolution:   'Pending resolution',
  resolved:             'Resolved',
  closed:               'Closed',
}

function rowAction(c: Claim, navigate: (p: string) => void): JSX.Element {
  if (c.status === 'filed') {
    return <Button variant="accent" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/claims/${c.id}`) }}>Start inspection</Button>
  }
  if (c.status === 'under_inspection' || c.status === 'inspection_complete') {
    return <Button variant="primary" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/claims/${c.id}`) }}>Complete</Button>
  }
  if (c.status === 'pending_resolution') {
    return <Button variant="accent" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/claims/${c.id}`) }}>Resolve</Button>
  }
  return <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/claims/${c.id}`) }}>View</Button>
}

export function ClaimList(): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()
  const [statusFilter, setStatusFilter] = useState<DamageClaimStatus | null>(null)
  const [search, setSearch] = useState('')
  // "Filed within" — null/'' means no date filter (show everything), same
  // opt-in-only rationale as BillingList/ContainerList's date filters.
  const filedRange = useDateRangeFilter()

  const isStaff = session?.role === 'nigeria_office_staff' || session?.role === 'tenant_admin'

  useTopBarSlot({
    actions: isStaff ? (
      <Button variant="primary" icon="plus" onClick={() => navigate('/claims/new')}>
        Log claim
      </Button>
    ) : null,
  })

  // Tenant-wide claim aggregates — SQL-computed server-side (GET /v1/claims/stats)
  // so the figures stay correct as claims grow to tens of thousands, instead of
  // counting a capped fetched sample.
  const { data: stats } = useQuery({
    queryKey: claimKeys.stats(),
    queryFn: () => claimsApi.stats(),
    staleTime: STALE_5_MIN,
  })

  const { sort, onSort, sortField, sortDirection } = useTableSort(SORT_COLUMNS)

  const { items: claims, isLoading, error, hasMore, loadMore, isFetchingMore, totalCount } = useClaimList({
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(search ? { q: search } : {}),
    ...(filedRange.createdAfter ? { created_after: filedRange.createdAfter } : {}),
    ...(filedRange.createdBefore ? { created_before: filedRange.createdBefore } : {}),
    ...(sortField ? { sort: sortField, direction: sortDirection } : {}),
  })

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load claims">{error.message}</Banner>
        </div>
      )}

      {/* KPI stats */}
      <div className={styles.statsRow}>
        <StatCard label="Open claims"        value={stats?.open ?? 0}          sublabel="filed + in progress" icon="warn" />
        <StatCard label="Under inspection"   value={stats?.under_inspection ?? 0} sublabel="delegate visits"  icon="search" />
        <StatCard label="Resolved (30d)"     value={stats?.resolved_30d ?? 0}   sublabel="avg 3.2d to resolve" icon="check" />
        <StatCard label="Total claims"       value={stats?.total ?? 0}         sublabel="all time"             icon="coin" />
      </div>

      {/* Filter bar */}
      <Card padding="default" style={{ marginBottom: 'var(--space-4)' }}>
        <div className={styles.filterRow}>
          <div className={styles.chips}>
            <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
              All{stats && <span className={styles.chipCount}>{stats.total}</span>}
            </Chip>
            {STATUS_FILTERS.map(({ key, label }) => (
              <Chip key={key} active={statusFilter === key} onClick={() => setStatusFilter(key)}>
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
              placeholder="Claim ID, customer, container…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <DateRangeFilter value={filedRange.daysBack} onChange={filedRange.handlePreset} />
          <div className={styles.customDateWrap}>
            <label htmlFor="claim_filed_from" className={styles.customDateLabel}>From</label>
            <input
              id="claim_filed_from"
              type="date"
              className={styles.customDateInput}
              value={filedRange.dateFrom}
              max={filedRange.dateTo || undefined}
              onChange={(e) => filedRange.handleCustomFrom(e.target.value)}
            />
            <label htmlFor="claim_filed_to" className={styles.customDateLabel}>To</label>
            <input
              id="claim_filed_to"
              type="date"
              className={styles.customDateInput}
              value={filedRange.dateTo}
              min={filedRange.dateFrom || undefined}
              onChange={(e) => filedRange.handleCustomTo(e.target.value)}
            />
          </div>
        </div>
      </Card>

      {/* Table */}
      <Card padding="none">
        <Table
          columns={[
            { title: 'Claim ID', sortable: true },
            { title: 'Customer' },
            { title: 'Container' },
            { title: 'Cartons affected' },
            { title: 'Description' },
            { title: 'Inspection' },
            { title: 'Status' },
            { title: 'Filed', sortable: true },
            { title: '', width: '130px' },
          ]}
          rows={claims.map((c) => ({
            cells: [
              <Mono key="id" color="var(--color-ink)">{c.reference ?? c.id.slice(0, 8)}</Mono>,
              c.customer_name
                ? <UserCell key="cust" name={c.customer_name} email="" />
                : <span key="cust" style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-sm)' }}>—</span>,
              <Mono key="ctn">{c.container_number ?? '—'}</Mono>,
              <div key="cartons" className={styles.cartonTags}>
                {c.cartons_affected.length > 0
                  ? c.cartons_affected.slice(0, 2).map((tag) => (
                      <span key={tag} className={styles.cartonTag}>{tag}</span>
                    ))
                  : <span style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-xs)' }}>—</span>}
                {c.cartons_affected.length > 2 && (
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>+{c.cartons_affected.length - 2}</span>
                )}
              </div>,
              <span key="desc" className={styles.descCell} title={c.description ?? undefined}>
                {c.description ?? '—'}
              </span>,
              c.inspection_method
                ? <Badge key="method" variant={c.inspection_method === 'delegate_visit' ? 'info' : 'neutral'} size="sm">
                    {c.inspection_method === 'delegate_visit' ? 'Delegate visit' : 'Customer evidence'}
                  </Badge>
                : <span key="method" style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-xs)' }}>—</span>,
              <Badge key="status" variant={STATUS_VARIANT[c.status]}>{STATUS_LABEL[c.status]}</Badge>,
              <span key="filed" className={styles.metaText}>
                {formatDate(c.created_at, 'short')}
              </span>,
              <div key="action" className={styles.rowActions}>{rowAction(c, navigate)}</div>,
            ],
          }))}
          loading={isLoading}
          emptyState={!isLoading && claims.length === 0 ? <span>No claims match this filter.</span> : undefined}
          sort={sort}
          onSort={onSort}
        />
      </Card>

      <ListFooter
        shown={claims.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="claims"
      />

      <div className={styles.subLinks}>
        <button className={styles.subLink} onClick={() => navigate('/claims/missing-items')}>Missing items →</button>
        <button className={styles.subLink} onClick={() => navigate('/claims/seized-items')}>Seized items →</button>
      </div>
    </div>
  )
}
