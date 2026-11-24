import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../../api/client'
import { formatCbm } from '../../../api/decimal'
import { containersApi, type ContainerStatus, type Container, type ContainerEvent } from '../../../api/tracking'
import { canApproveOrReject, formatPackageMix } from '../../../api/packingListRules'
import { packingListApi, type PackingList, type PackingListStatus } from '../../../api/packingList'
import { useSession } from '../../../auth/useSession'
import { Badge, Banner, Button, Card, Chip, ExportButton, Mono, SearchField, StatusBadge, Table, type TableSort, UserCell, EmptyState } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../ContainerDetail.module.css'
import { formatDate, formatKg, formatTime, plural } from '../../../lib/format'
import { eventLabel, humanRole } from './labels'
import { useListExport } from '../../../hooks/useListExport'
import { statusLabel, statusVariant } from '../../../design/status'
import { toast } from '../../../design/toast'

const PL_STATUSES: PackingListStatus[] = ['draft', 'pending_approval', 'approved', 'rejected']

/** Every packing list on the container, searchable, filterable, sortable, with inline bulk submit/approve. */
export function PackingListsTab({
  containerId,
  packingLists,
  canAdd,
  initialSearch = '',
  onChanged,
}: {
  containerId: string
  packingLists: PackingList[]
  canAdd: boolean
  initialSearch?: string
  onChanged?: () => void
}): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()
  const canBulkAct = session?.role === 'china_office_staff' || session?.role === 'tenant_admin'
  const [search, setSearch] = useState(initialSearch)
  const [statusFilter, setStatusFilter] = useState<PackingListStatus | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)
  // 'Ref #' sort on the packing-lists sub-table — this list is already fully
  // loaded in memory for one container (not a paginated endpoint), so sorting
  // is pure client-side: no query param, no backend change.
  const [plSortDirection, setPlSortDirection] = useState<TableSort['direction'] | null>(null)

  const filteredPackingLists = useMemo(() => {
    const q = search.trim().toLowerCase()
    return packingLists.filter((pl) => {
      if (statusFilter && pl.status !== statusFilter) return false
      if (!q) return true
      return [pl.reference, pl.customer_name, pl.customer_phone]
        .filter(Boolean)
        .some((v) => v!.toLowerCase().includes(q))
    })
  }, [packingLists, search, statusFilter])

  const sortedPackingLists = useMemo(() => {
    if (!plSortDirection) return filteredPackingLists
    const sorted = [...filteredPackingLists].sort((a, b) =>
      (a.reference ?? '').localeCompare(b.reference ?? ''),
    )
    return plSortDirection === 'asc' ? sorted : sorted.reverse()
  }, [filteredPackingLists, plSortDirection])

  const plTableSort: TableSort | undefined = plSortDirection
    ? { columnIndex: 0, direction: plSortDirection }
    : undefined

  function togglePlSort(): void {
    setPlSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
  }

  function toggleRow(id: string, isSelected: boolean): void {
    setSelected((prev) => {
      const next = new Set(prev)
      if (isSelected) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function toggleAll(isSelected: boolean): void {
    const eligible = sortedPackingLists.filter((pl) => pl.status === 'draft' || pl.status === 'pending_approval')
    setSelected(isSelected ? new Set(eligible.map((pl) => pl.id)) : new Set())
  }

  const selectedPls = sortedPackingLists.filter((pl) => selected.has(pl.id))
  const submittableIds = selectedPls.filter((pl) => pl.status === 'draft').map((pl) => pl.id)
  const approvableIds = (session
    ? selectedPls.filter((pl) => canApproveOrReject(pl, session.role, session.userId))
    : selectedPls
  ).map((pl) => pl.id)

  async function handleBulkSubmit(): Promise<void> {
    if (submittableIds.length === 0) return
    setBulkBusy(true)
    setBulkError(null)
    try {
      const res = await packingListApi.bulkSubmit(submittableIds)
      if (res.succeeded.length) toast.success(`${plural(res.succeeded.length, 'packing list')} submitted`)
      setSelected(new Set())
      onChanged?.()
    } catch (err) {
      setBulkError(err instanceof ApiError ? err.message : 'Bulk submit failed.')
    } finally {
      setBulkBusy(false)
    }
  }

  async function handleBulkApprove(): Promise<void> {
    if (approvableIds.length === 0) return
    setBulkBusy(true)
    setBulkError(null)
    try {
      const res = await packingListApi.bulkApprove(approvableIds)
      if (res.succeeded.length) toast.success(`${plural(res.succeeded.length, 'packing list')} approved`)
      setSelected(new Set())
      onChanged?.()
    } catch (err) {
      setBulkError(err instanceof ApiError ? err.message : 'Bulk approve failed.')
    } finally {
      setBulkBusy(false)
    }
  }

  return (
    <Card padding="none">
      <div className={styles.tableHead}>
        <SectionHead
          title="Packing lists on this container"
          sub={
            filteredPackingLists.length === packingLists.length
              ? plural(packingLists.length, 'packing list')
              : `${filteredPackingLists.length} of ${plural(packingLists.length, 'packing list')}`
          }
        />
        {canAdd && (
          <Button
            variant="primary"
            size="sm"
            icon="plus"
            onClick={() => navigate(`/packing-lists/new?container_id=${encodeURIComponent(containerId)}`)}
          >
            Add packing list
          </Button>
        )}
      </div>

      {packingLists.length > 0 && (
        <div className={styles.plFilterRow}>
          <div className={styles.plChips}>
            <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
              All
            </Chip>
            {PL_STATUSES.map((s) => {
              const count = packingLists.filter((pl) => pl.status === s).length
              if (count === 0) return null
              return (
                <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(statusFilter === s ? null : s)}>
                  {statusLabel('packingList', s)} · {count}
                </Chip>
              )
            })}
          </div>
          <SearchField
            label="Search container packing lists"
            placeholder="Ref #, customer, phone…"
            value={search}
            onChange={setSearch}
          />
        </div>
      )}

      {bulkError && (
        <div style={{ padding: '0 var(--space-5) var(--space-3)' }}>
          <Banner variant="error" title="Bulk action failed" dismissible onDismiss={() => setBulkError(null)}>
            {bulkError}
          </Banner>
        </div>
      )}

      {canBulkAct && selectedPls.length > 0 && (
        <div className={styles.plBulkBar}>
          <span className={styles.plBulkLabel}>{plural(selectedPls.length, 'packing list')} selected</span>
          <div className={styles.plBulkActions}>
            <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
            {submittableIds.length > 0 && (
              <Button variant="secondary" size="sm" icon="arrowright" loading={bulkBusy} onClick={() => void handleBulkSubmit()}>
                Submit · {submittableIds.length}
              </Button>
            )}
            {approvableIds.length > 0 && (
              <Button variant="primary" size="sm" icon="check" loading={bulkBusy} onClick={() => void handleBulkApprove()}>
                Approve · {approvableIds.length}
              </Button>
            )}
          </div>
        </div>
      )}

      <Table
        selectable={canBulkAct}
        columns={[
          { title: 'Ref #', type: 'reference', sortable: true },
          { title: 'Customer' },
          { title: 'Contact' },
          { title: 'Packages', type: 'number' },
          { title: 'Volume (CBM)', type: 'number' },
          { title: 'Weight (kg)', type: 'number' },
          { title: 'Status', type: 'status' },
          { title: 'Submitted', type: 'date' },
        ]}
        rows={sortedPackingLists.map((pl) => ({
          selected: selected.has(pl.id),
          selectable: pl.status === 'draft' || pl.status === 'pending_approval',
          onOpen: () => navigate(`/packing-lists/${pl.id}`),
          cells: [
            <Mono key="ref" color="var(--color-ink)">
              {pl.reference ?? '—'}
            </Mono>,
            <span key="customer">{pl.customer_name ?? '—'}</span>,
            pl.customer_phone ? (
              <Mono key="phone">{pl.customer_phone}</Mono>
            ) : (
              <span key="phone" style={{ color: 'var(--color-ink-4)' }}>
                —
              </span>
            ),
            <span key="cartons">{formatPackageMix(pl.package_mix)}</span>,
            <Mono key="cbm">{formatCbm(pl.total_cbm)}</Mono>,
            <Mono key="weight">
              {pl.total_weight_kg ? `${formatKg(pl.total_weight_kg)} kg` : '—'}
            </Mono>,
            <StatusBadge key="status" kind="packingList" status={pl.status} />,
            <span key="submitted" className={styles.metaText}>
              {formatDate(pl.created_at, 'short')}
            </span>,
          ],
        }))}
        emptyState={
          packingLists.length > 0 ? (
            <EmptyState
              compact
              title="No packing lists match this filter"
              action={{
                label: 'Clear filters',
                onClick: () => {
                  setSearch('')
                  setStatusFilter(null)
                },
              }}
            />
          ) : (
            <EmptyState compact title="No packing lists yet" body="Add one to get started." />
          )
        }
        onSelectRow={(rowIndex, isSelected) => {
          const pl = sortedPackingLists[rowIndex]
          if (pl) toggleRow(pl.id, isSelected)
        }}
        onSelectAll={toggleAll}
        sort={plTableSort}
        onSort={togglePlSort}
      />
    </Card>
  )
}

/** The tracking tab: full event log, newest first (pipeline stepper lives in DetailPage.progress). */
export function TrackingTab({
  container,
  events,
}: {
  container: Container
  events: ContainerEvent[]
}): JSX.Element {
  const exportEvents = useListExport((format: 'xlsx' | 'csv') => containersApi.exportEvents(container.id, format))
  return (
    <Card padding="none">
      <div className={styles.tableHead}>
        <SectionHead
          title="Event log"
          sub={`All tracking events for ${container.container_number}, newest first`}
          action={<ExportButton formats={['xlsx', 'csv']} size="sm" onExport={exportEvents.onExport} />}
        />
      </div>
      {exportEvents.error && (
        <Banner variant="error" title="Couldn't export the event log" dismissible onDismiss={exportEvents.dismissError}>
          {exportEvents.error}
        </Banner>
      )}
      <Table
        columns={[
          { title: 'Timestamp', type: 'date' },
          { title: 'Event' },
          { title: 'Status change' },
          { title: 'Updated by' },
          { title: 'Notes' },
        ]}
        rows={[...events].reverse().map((event) => ({
          cells: [
            <Mono key="ts">
              {formatDate(event.created_at, 'short')} {formatTime(event.created_at)}
            </Mono>,
            <Badge key="event" variant={statusVariant('container', event.to_status)}>
              {eventLabel(event.from_status, event.to_status)}
            </Badge>,
            <span key="change" className={styles.statusChange}>
              <span className={styles.statusFrom}>
                {statusLabel('container', event.from_status as ContainerStatus)}
              </span>
              <span className={styles.statusArrow}>→</span>
              <strong className={styles.statusTo}>
                {statusLabel('container', event.to_status as ContainerStatus)}
              </strong>
            </span>,
            event.actor_name ? (
              <UserCell key="actor" name={event.actor_name} email={humanRole(event.actor_role)} />
            ) : (
              <span key="actor" className={styles.eventNote}>
                —
              </span>
            ),
            <span key="notes" className={styles.eventNote}>
              {event.notes ?? '—'}
            </span>,
          ],
        }))}
        emptyState={<EmptyState compact title="No tracking events yet" />}
      />
    </Card>
  )
}
