import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { claimsApi, type Claim, type DamageClaimStatus } from '../../api/claims'
import { claimKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Badge, Button, Chip, DateRangeFilter, ListFooter, Mono, StatCard, StatusBadge, Table, UserCell, SearchField, EmptyState, ErrorState } from '../../design/components'
import { useSession } from '../../auth/useSession'
import { useClaimList } from '../../hooks/useClaims'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { type SortableColumn, useTableSort } from '../../hooks/useTableSort'
import styles from './ClaimList.module.css'
import { formatDate } from '../../lib/format'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage, StatRow } from '../../shell/ListPage'
import { statusLabel } from '../../design/status'
import { PageHeader } from '../../shell/PageHeader'

// 'Claim ID' (reference, text) defaults asc; 'Filed' (created_at) defaults
// desc (newest first) — same convention as BillingList/ContainerList.
const SORT_COLUMNS: SortableColumn[] = [
  { index: 0, field: 'reference', defaultDirection: 'asc' },
  { index: 7, field: 'created_at', defaultDirection: 'desc' },
]

// The claim stages a list filters on, in the status registry's words (FD-08).
const STATUS_FILTERS: Array<{ key: DamageClaimStatus; label: string }> = (
  ['filed', 'under_inspection', 'pending_resolution', 'resolved', 'closed'] as const
).map((key) => ({ key, label: statusLabel('claim', key) }))

/** The row's next step, or nothing: opening the row itself is how you view a claim (FD-13). */
function rowAction(c: Claim, navigate: (p: string) => void): JSX.Element | null {
  if (c.status === 'filed') {
    return <Button variant="secondary" size="sm" mutates={false} onClick={(e) => { e.stopPropagation(); navigate(`/claims/${c.id}`) }}>Start inspection</Button>
  }
  if (c.status === 'under_inspection' || c.status === 'inspection_complete') {
    return <Button variant="secondary" size="sm" mutates={false} onClick={(e) => { e.stopPropagation(); navigate(`/claims/${c.id}`) }}>Complete</Button>
  }
  if (c.status === 'pending_resolution') {
    return <Button variant="secondary" size="sm" mutates={false} onClick={(e) => { e.stopPropagation(); navigate(`/claims/${c.id}`) }}>Resolve</Button>
  }
  return null
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

  // Tenant-wide claim aggregates — SQL-computed server-side (GET /v1/claims/stats)
  // so the figures stay correct as claims grow to tens of thousands, instead of
  // counting a capped fetched sample.
  const { data: stats } = useQuery({
    queryKey: claimKeys.stats(),
    queryFn: () => claimsApi.stats(),
    staleTime: STALE_5_MIN,
  })

  const { sort, onSort, sortField, sortDirection } = useTableSort(SORT_COLUMNS)

  const { items: claims, isLoading, error, hasMore, loadMore, isFetchingMore, totalCount, refetch } = useClaimList({
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(search ? { q: search } : {}),
    ...(filedRange.createdAfter ? { created_after: filedRange.createdAfter } : {}),
    ...(filedRange.createdBefore ? { created_before: filedRange.createdBefore } : {}),
    ...(sortField ? { sort: sortField, direction: sortDirection } : {}),
  })

  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Damage claims"
            primary={
              isStaff && (
                <Button variant="primary" icon="plus" onClick={() => navigate('/claims/new')}>
                  Log claim
                </Button>
              )
            }
          />
        }
        notices={
          <>
            {error && (
              <ErrorState
                compact
                title="Couldn't load claims"
                error={error}
                onRetry={() => void refetch()}
              />
            )}
          </>
        }
        stats={
          <StatRow>
            <StatCard
              label="Filed"
              value={stats?.filed ?? 0}
              sublabel="to inspect"
              icon="flag"
              selected={statusFilter === 'filed'}
              onSelect={() => setStatusFilter(statusFilter === 'filed' ? null : 'filed')}
            />
            <StatCard
              label="Under inspection"
              value={stats?.under_inspection ?? 0}
              sublabel="delegate visits"
              icon="search"
              selected={statusFilter === 'under_inspection'}
              onSelect={() =>
                setStatusFilter(statusFilter === 'under_inspection' ? null : 'under_inspection')
              }
            />
            <StatCard
              label="Pending resolution"
              value={stats?.pending_resolution ?? 0}
              sublabel="to decide"
              icon="clock"
              selected={statusFilter === 'pending_resolution'}
              onSelect={() =>
                setStatusFilter(statusFilter === 'pending_resolution' ? null : 'pending_resolution')
              }
            />
            <StatCard
              label="Resolved (30 days)"
              value={stats?.resolved_30d ?? 0}
              sublabel="decided this month"
              icon="check"
              selected={statusFilter === 'resolved'}
              onSelect={() => setStatusFilter(statusFilter === 'resolved' ? null : 'resolved')}
            />
          </StatRow>
        }
        filters={
          <FilterBar
            label="Filter damage claims"
            status={
              <>
                <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
                  All{stats && <span className={styles.chipCount}>{stats.total}</span>}
                </Chip>
                {STATUS_FILTERS.map(({ key, label }) => (
                  <Chip
                    key={key}
                    active={statusFilter === key}
                    onClick={() => setStatusFilter(key)}
                  >
                    {label}
                    {stats && (
                      <span className={styles.chipCount}>
                        {Number(stats[key as keyof typeof stats] ?? 0)}
                      </span>
                    )}
                  </Chip>
                ))}
              </>
            }
            search={
              <>
                <SearchField
                  label="Search claims"
                  placeholder="Claim ID, customer, container…"
                  value={search}
                  onChange={setSearch}
                />
              </>
            }
            dateRange={
              <>
                <DateRangeFilter label="Filed" range={filedRange} />
              </>
            }
          />
        }
        footer={
          <ListFooter
            shown={claims.length}
            total={totalCount}
            hasMore={hasMore}
            loading={isFetchingMore}
            onLoadMore={loadMore}
            noun="claims"
            nounOne="claim"
          />
        }
      >
        <Table
          columns={[
            { title: 'Claim ID', type: 'reference', sortable: true },
            { title: 'Customer' },
            { title: 'Container', type: 'reference' },
            { title: 'Cartons affected', type: 'number' },
            { title: 'Description' },
            { title: 'Inspection' },
            { title: 'Status', type: 'status' },
            { title: 'Filed', type: 'date', sortable: true },
            { title: '', type: 'action', width: '130px' },
          ]}
          rows={claims.map((c) => ({
            onOpen: () => navigate(`/claims/${c.id}`),
            openLabel: c.reference ? `Open claim ${c.reference}` : 'Open claim',
            cells: [
              <Mono key="id" color="var(--color-ink)">
                {c.reference ?? c.id.slice(0, 8)}
              </Mono>,
              c.customer_name ? (
                <UserCell key="cust" name={c.customer_name} email="" />
              ) : (
                <span
                  key="cust"
                  style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-sm)' }}
                >
                  —
                </span>
              ),
              <Mono key="ctn">{c.container_number ?? '—'}</Mono>,
              <div key="cartons" className={styles.cartonTags}>
                {c.cartons_affected.length > 0 ? (
                  c.cartons_affected.slice(0, 2).map((tag) => (
                    <span key={tag} className={styles.cartonTag}>
                      {tag}
                    </span>
                  ))
                ) : (
                  <span style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-xs)' }}>—</span>
                )}
                {c.cartons_affected.length > 2 && (
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>
                    +{c.cartons_affected.length - 2}
                  </span>
                )}
              </div>,
              <span key="desc" className={styles.descCell} title={c.description ?? undefined}>
                {c.description ?? '—'}
              </span>,
              c.inspection_method ? (
                <Badge
                  key="method"
                  variant={c.inspection_method === 'delegate_visit' ? 'info' : 'neutral'}
                  size="sm"
                >
                  {c.inspection_method === 'delegate_visit'
                    ? 'Delegate visit'
                    : 'Customer evidence'}
                </Badge>
              ) : (
                <span
                  key="method"
                  style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-xs)' }}
                >
                  —
                </span>
              ),
              <StatusBadge key="status" kind="claim" status={c.status} />,
              <span key="filed" className={styles.metaText}>
                {formatDate(c.created_at, 'short')}
              </span>,
              <div key="action" className={styles.rowActions}>
                {rowAction(c, navigate)}
              </div>,
            ],
          }))}
          loading={isLoading}
          emptyState={
            !isLoading && claims.length === 0 ? (
              <EmptyState compact title="No claims match this filter" />
            ) : undefined
          }
          sort={sort}
          onSort={onSort}
        />
      </ListPage>
    </>
  )
}
