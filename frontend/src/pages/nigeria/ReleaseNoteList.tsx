import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ReleaseNoteStatus } from '../../api/releaseNotes'
import { releaseTypeLabel } from '../../api/releaseNotesRules'
import { useReleaseNoteList, useReleaseNoteStats } from '../../hooks/useReleaseNotes'
import { Banner, Card, Chip, ListFooter, Mono, StatCard, StatusBadge, Table, ViewLink } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './ReleaseNoteList.module.css'
import { formatDate } from '../../lib/format'
import { statusLabel } from '../../design/status'

const STATUS_FILTERS: ReleaseNoteStatus[] = ['active', 'picked_up', 'expired', 'cancelled']


export function ReleaseNoteList(): JSX.Element {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<ReleaseNoteStatus | null>(null)
  const { items: notes, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount } = useReleaseNoteList(
    statusFilter ? { status: statusFilter } : {},
  )

  // §9.1 stats row (P2-3) — real per-status counts from GET /stats; hidden until loaded, and on failure.
  const { data: stats = null } = useReleaseNoteStats()

  useTopBarSlot({ subtitle: 'Authorise and track carton pickups from the warehouse.' })

  return (
    <div>

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load release notes">{error.message}</Banner>
        </div>
      )}

      {stats && (
        <div className={styles.statsRow}>
          <StatCard label="Active · awaiting pickup" value={stats.active} icon="card" />
          <StatCard label="Picked up today" value={stats.picked_up_today} icon="check" />
          <StatCard
            label="Partial pickups"
            value={stats.partial_active}
            icon="package"
            sublabel={stats.partial_active > 0 ? 'awaiting follow-up' : 'none open'}
          />
          <StatCard
            label="Expired · uncollected"
            value={stats.expired}
            icon="warn"
            sublabel={stats.expired > 0 ? 'contact the customer' : 'all clear'}
          />
        </div>
      )}

      <Card padding="default">
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>All</Chip>
          {STATUS_FILTERS.map((s) => (
            <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
              {statusLabel('releaseNote', s)}
            </Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding="none">
          <Table
            columns={[
              { title: 'Reference' },
              { title: 'Customer' },
              { title: 'Container' },
              { title: 'Cartons', align: 'right' },
              { title: 'Type' },
              { title: 'Status' },
              { title: 'Issued' },
              { title: '', width: '60px' },
            ]}
            rows={notes.map((n) => ({
              cells: [
                <Mono key="ref">{n.reference_number}</Mono>,
                <span key="cust">{n.customer_name ?? '—'}</span>,
                <Mono key="con">{n.container_number ?? '—'}</Mono>,
                <Mono key="cartons">{n.carton_count} / {n.total_cartons_for_customer}</Mono>,
                <span key="type" className={styles.partial}>{releaseTypeLabel(n)}</span>,
                <StatusBadge key="status" kind="releaseNote" status={n.status} />,
                <span key="date">{formatDate(n.authorized_at)}</span>,
                <ViewLink key="view" onClick={() => navigate(`/release-notes/${n.id}`, { state: { note: n } })} />,
              ],
            }))}
            loading={loading}
            emptyState={!loading && notes.length === 0 ? <span>✓ No release notes match this filter.</span> : undefined}
          />
        </Card>
        <ListFooter
        shown={notes.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="release notes"
      />
      </div>
    </div>
  )
}
