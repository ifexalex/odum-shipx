import { useEffect, useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatCbm } from '../../api/decimal'
import { manifestApi, orderedPackageMix, type Manifest, type VerificationStatus } from '../../api/manifest'
import { isManifestOverdue as isOverdue } from '../../api/manifestRules'
import { useManifestList } from '../../hooks/useManifests'
import { Badge, Banner, Card, Chip, Mono, StatCard, Table, ViewLink, ListFooter, type BadgeVariant } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './ManifestList.module.css'
import { formatNumber } from '../../lib/format'

// Per-status counts come from GET /v1/manifests/stats (P2-4) — a single
// aggregate query, so no page-tallying. Chips still set the real
// verification_status query param and refetch.
const STATUS_FILTERS: VerificationStatus[] = ['pending', 'verified', 'discrepancies_found', 'resolved']

const STATUS_VARIANT: Record<VerificationStatus, BadgeVariant> = {
  pending: 'warning',
  verified: 'success',
  discrepancies_found: 'error',
  resolved: 'neutral',
}

function statusLabel(status: VerificationStatus): string {
  if (status === 'discrepancies_found') return 'Discrepancies found'
  return status[0]!.toUpperCase() + status.slice(1)
}

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
  return `${formatNumber(n, 0)} kg`
}

type ManifestStats = Awaited<ReturnType<typeof manifestApi.stats>>

export function ManifestList(): JSX.Element {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<VerificationStatus | null>(null)
  const [stats, setStats] = useState<ManifestStats | null>(null)

  const { items: manifests, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount } = useManifestList(
    statusFilter ? { verification_status: statusFilter } : {},
  )

  const overdueCount = useMemo(() => manifests.filter(isOverdue).length, [manifests])

  // §6.2 stats row (P2-4) — real per-status counts; hidden on failure.
  useEffect(() => {
    void manifestApi.stats().then(setStats).catch(() => setStats(null))
  }, [])

  useTopBarSlot({ subtitle: 'Verify incoming container cargo against the packing list.' })

  return (
    <div>

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

      <Card padding={16}>
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
            All
          </Chip>
          {STATUS_FILTERS.map((status) => (
            <Chip key={status} active={statusFilter === status} onClick={() => setStatusFilter(status)}>
              {statusLabel(status)}
            </Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding={0}>
          <Table
            columns={[
              { title: 'Container' },
              { title: 'Customers', align: 'right' },
              { title: 'Packages' },
              { title: 'CBM', align: 'right' },
              { title: 'Weight', align: 'right' },
              { title: 'Status' },
              { title: '', width: '40px' },
            ]}
            rows={manifests.map((mf) => {
              const overdue = isOverdue(mf)
              return {
                suspended: overdue,
                cells: [
                  <Mono key="container">{mf.container_number ?? mf.container_id}</Mono>,
                  <Mono key="customers">{mf.total_customers}</Mono>,
                  <PackageMix key="packages" manifest={mf} />,
                  <Mono key="cbm">{formatCbm(mf.total_cbm)}</Mono>,
                  <span key="weight" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{fmtWeight(mf.total_weight_kg)}</span>,
                  <span key="status" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <Badge variant={STATUS_VARIANT[mf.verification_status]}>
                      {statusLabel(mf.verification_status)}
                    </Badge>
                    {overdue && <Badge variant="error" size="sm">Overdue</Badge>}
                  </span>,
                  <ViewLink key="view" onClick={() => navigate(`/manifests/${mf.id}`)} />,
                ],
              }
            })}
            loading={loading}
            emptyState={!loading && manifests.length === 0 ? <span>No manifests yet.</span> : undefined}
          />
        </Card>
        <ListFooter
        shown={manifests.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="manifests"
      />
      </div>
    </div>
  )
}
