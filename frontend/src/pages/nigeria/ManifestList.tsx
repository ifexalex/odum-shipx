import { useMemo, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatCbm } from '../../api/decimal'
import { orderedPackageMix, type Manifest, type VerificationStatus } from '../../api/manifest'
import { isManifestOverdue as isOverdue } from '../../api/manifestRules'
import { useManifestList, useManifestStats } from '../../hooks/useManifests'
import { Badge, Banner, Card, Chip, ListFooter, Mono, StatCard, StatusBadge, Table, EmptyState } from '../../design/components'
import styles from './ManifestList.module.css'
import { formatKg } from '../../lib/format'
import { useStatusParam } from '../../lib/useStatusParam'
import { statusLabel } from '../../design/status'
import { PageHeader } from '../../shell/PageHeader'

// Per-status counts come from GET /v1/manifests/stats (P2-4) — a single
// aggregate query, so no page-tallying. Chips still set the real
// verification_status query param and refetch.
const STATUS_FILTERS: VerificationStatus[] = ['pending', 'verified', 'discrepancies_found', 'resolved']

// Package breakdown per container — "120 ctn · 8 bale · 30 bag" — so staff see
// what kinds of goods are inside, not just a single (misleading) carton count.
function PackageMix({ manifest }: { manifest: Manifest }): JSX.Element {
  const parts = orderedPackageMix(manifest.package_mix)
  if (parts.length === 0) {
    return <Mono>{manifest.total_cartons || '—'}</Mono>
  }
  return (
    <span className={styles.mix}>
      {parts.map((p, i) => (
        <span key={p.unit} className={styles.mixPart}>
          {i > 0 && <span className={styles.mixDot}>·</span>}
          <Mono>{p.qty}</Mono>
          <span className={styles.mixUnit}>{p.abbr}</span>
        </span>
      ))}
    </span>
  )
}

function fmtWeight(kg: string | null | undefined): string {
  const n = Number(kg)
  if (!kg || Number.isNaN(n) || n === 0) return '—'
  return `${formatKg(n)} kg`
}

// The values `?status=` may hold (useStatusParam); anything else reads as no filter.
const VERIFICATION_STATUSES: readonly VerificationStatus[] = ['pending', 'verified', 'discrepancies_found', 'resolved']

export function ManifestList(): JSX.Element {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useStatusParam<VerificationStatus>(VERIFICATION_STATUSES)
  const { items: manifests, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount } = useManifestList(
    statusFilter ? { verification_status: statusFilter } : {},
  )

  const overdueCount = useMemo(() => manifests.filter(isOverdue).length, [manifests])

  // §6.2 stats row (P2-4) — real per-status counts; hidden until loaded, and on failure.
  const { data: stats = null } = useManifestStats()

  return (
    <div>
      <PageHeader
        title="Manifests"
        meta={'Verify incoming container cargo against the packing list.'}
      />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Something went wrong">{error.message}</Banner>
        </div>
      )}

      {stats && (
        <div className={styles.statsRow}>
          <StatCard
            label="Awaiting verification"
            value={stats.pending}
            icon="clock"
            sublabel={stats.overdue > 0 ? `${stats.overdue} overdue — container arrived` : 'none overdue'}
          />
          <StatCard label="Verified" value={stats.verified} icon="check" />
          <StatCard label="With discrepancies" value={stats.discrepancies_found} icon="warn" />
          <StatCard label="Resolved" value={stats.resolved} icon="flag" />
        </div>
      )}

      {overdueCount > 0 && (
        <div className={styles.banner}>
          <Banner variant="warning" icon="alert" title={`${overdueCount} manifest${overdueCount === 1 ? '' : 's'} overdue for verification`}>
            {overdueCount === 1 ? 'This container has' : 'These containers have'} arrived in Nigeria but{' '}
            {overdueCount === 1 ? 'its manifest is' : 'their manifests are'} still unverified — verify to unblock billing and release.
          </Banner>
        </div>
      )}

      <Card padding="default">
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
            All
          </Chip>
          {STATUS_FILTERS.map((status) => (
            <Chip key={status} active={statusFilter === status} onClick={() => setStatusFilter(status)}>
              {statusLabel('manifest', status)}
            </Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding="none">
          <Table
            columns={[
              { title: 'Container', type: 'reference' },
              { title: 'Customers', type: 'number' },
              { title: 'Packages', type: 'number' },
              { title: 'Volume (CBM)', type: 'number' },
              { title: 'Weight (kg)', type: 'number' },
              { title: 'Status', type: 'status' },
            ]}
            rows={manifests.map((mf) => {
              const overdue = isOverdue(mf)
              return {
                suspended: overdue,
                onOpen: () => navigate(`/manifests/${mf.id}`),
                cells: [
                  <Mono key="container">{mf.container_number ?? mf.container_id}</Mono>,
                  <Mono key="customers">{mf.total_customers}</Mono>,
                  <PackageMix key="packages" manifest={mf} />,
                  <Mono key="cbm">{formatCbm(mf.total_cbm)}</Mono>,
                  <span key="weight" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>{fmtWeight(mf.total_weight_kg)}</span>,
                  <span key="status" style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                    <StatusBadge kind="manifest" status={mf.verification_status} />
                    {overdue && <Badge variant="error" size="sm">Overdue</Badge>}
                  </span>,
                ],
              }
            })}
            loading={loading}
            emptyState={!loading && manifests.length === 0 ? <EmptyState compact title="No manifests yet" /> : undefined}
          />
        </Card>
        <ListFooter
        shown={manifests.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="manifests"
        nounOne="manifest"
      />
      </div>
    </div>
  )
}
