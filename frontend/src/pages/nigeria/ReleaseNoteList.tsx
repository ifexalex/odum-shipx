import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ReleaseNoteStatus } from '../../api/releaseNotes'
import { releaseTypeLabel } from '../../api/releaseNotesRules'
import { useReleaseNoteList, useReleaseNoteStats } from '../../hooks/useReleaseNotes'
import { Chip, ListFooter, Mono, SearchField, StatCard, StatusBadge, Table, EmptyState, ErrorState } from '../../design/components'
import styles from './ReleaseNoteList.module.css'
import { formatDate } from '../../lib/format'
import { useStatusParam } from '../../lib/useStatusParam'
import { statusLabel } from '../../design/status'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage, StatRow } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

const STATUS_FILTERS: ReleaseNoteStatus[] = ['active', 'picked_up', 'expired', 'cancelled']

export function ReleaseNoteList(): JSX.Element {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useStatusParam<ReleaseNoteStatus>(STATUS_FILTERS)
  const [search, setSearch] = useState('')
  const { items: notes, isLoading: loading, error, hasMore, loadMore, isFetchingMore, totalCount, refetch } = useReleaseNoteList(
    statusFilter ? { status: statusFilter } : {},
  )

  const filteredNotes = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return notes
    return notes.filter((n) =>
      [n.reference_number, n.customer_name, n.container_number]
        .filter(Boolean)
        .some((v) => v!.toLowerCase().includes(q)),
    )
  }, [notes, search])

  // §9.1 stats row (P2-3) — real per-status counts from GET /stats; hidden until loaded, and on failure.
  const { data: stats = null } = useReleaseNoteStats()

  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Release notes"
            meta={'Authorise and track carton pickups from the warehouse.'}
          />
        }
        notices={
          <>
            {error && (
              <ErrorState
                compact
                title="Couldn't load release notes"
                error={error}
                onRetry={() => void refetch()}
              />
            )}
          </>
        }
        stats={
          stats && (
            <StatRow>
              <StatCard
                label="Awaiting pickup"
                value={stats.active}
                icon="card"
                sublabel="active notes"
                selected={statusFilter === 'active'}
                onSelect={() => setStatusFilter(statusFilter === 'active' ? null : 'active')}
              />
              <StatCard
                label="Partial pickups"
                value={stats.partial_active}
                icon="package"
                sublabel={stats.partial_active > 0 ? 'awaiting follow-up' : 'none open'}
              />
              <StatCard
                label="Expired, uncollected"
                value={stats.expired}
                icon="warn"
                sublabel={stats.expired > 0 ? 'contact the customer' : 'all clear'}
                selected={statusFilter === 'expired'}
                onSelect={() => setStatusFilter(statusFilter === 'expired' ? null : 'expired')}
              />
            </StatRow>
          )
        }
        filters={
          <FilterBar
            label="Filter release notes"
            status={
              <>
                <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
                  All
                </Chip>
                {STATUS_FILTERS.map((s) => (
                  <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
                    {statusLabel('releaseNote', s)}
                  </Chip>
                ))}
              </>
            }
            search={
              <SearchField
                label="Search release notes"
                placeholder="Reference, customer, container…"
                value={search}
                onChange={setSearch}
              />
            }
          />
        }
        footer={
          <ListFooter
            shown={filteredNotes.length}
            total={search.trim() ? filteredNotes.length : totalCount}
            hasMore={!search.trim() && hasMore}
            loading={isFetchingMore}
            onLoadMore={loadMore}
            noun="release notes"
            nounOne="release note"
          />
        }
      >
        <Table
          columns={[
            { title: 'Reference', type: 'reference' },
            { title: 'Customer' },
            { title: 'Container', type: 'reference' },
            { title: 'Cartons', type: 'number' },
            { title: 'Type' },
            { title: 'Status', type: 'status' },
            { title: 'Issued', type: 'date' },
          ]}
          rows={filteredNotes.map((n) => ({
            onOpen: () => navigate(`/release-notes/${n.id}`, { state: { note: n } }),
            cells: [
              <Mono key="ref">{n.reference_number}</Mono>,
              <span key="cust">{n.customer_name ?? '—'}</span>,
              <Mono key="con">{n.container_number ?? '—'}</Mono>,
              <Mono key="cartons">
                {n.carton_count} / {n.total_cartons_for_customer}
              </Mono>,
              <span key="type" className={styles.partial}>
                {releaseTypeLabel(n)}
              </span>,
              <StatusBadge key="status" kind="releaseNote" status={n.status} />,
              <span key="date">{formatDate(n.authorized_at)}</span>,
            ],
          }))}
          loading={loading}
          emptyState={
            !loading && filteredNotes.length === 0 ? (
              <EmptyState compact title="No release notes match this filter" />
            ) : undefined
          }
        />
      </ListPage>
    </>
  )
}
