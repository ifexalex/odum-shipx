import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { CONTAINER_STATUS_LABELS } from '../../../api/containerRules'
import { formatCbm } from '../../../api/decimal'
import { containersApi, type ContainerStatus, type Container, type ContainerEvent } from '../../../api/tracking'
import { formatPackageMix } from '../../../api/packingListRules'
import {
  Badge,
  Banner,
  Button,
  Card,
  ExportButton,
  Mono,
  Table,
  UserCell,
  ViewLink,
  type TableSort,
} from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../ContainerDetail.module.css'
import { formatDate, formatTime } from '../../../lib/format'
import { eventLabel, eventBadgeVariant, humanRole, PL_STATUS_VARIANT } from './labels'
import { ContainerStepper } from './Timeline'
import { type PackingList } from '../../../api/packingList'
import { useListExport } from '../../../hooks/useListExport'

/** Every packing list on the container, sortable by reference. */
export function PackingListsTab({
  packingLists,
  canAdd,
}: {
  packingLists: PackingList[]
  canAdd: boolean
}): JSX.Element {
  const navigate = useNavigate()
  // 'Ref #' sort on the packing-lists sub-table — this list is already fully
  // loaded in memory for one container (not a paginated endpoint), so sorting
  // is pure client-side: no query param, no backend change.
  const [plSortDirection, setPlSortDirection] = useState<TableSort['direction'] | null>(null)
  const sortedPackingLists = useMemo(() => {
    if (!plSortDirection) return packingLists
    const sorted = [...packingLists].sort((a, b) =>
      (a.reference ?? '').localeCompare(b.reference ?? ''),
    )
    return plSortDirection === 'asc' ? sorted : sorted.reverse()
  }, [packingLists, plSortDirection])
  const plTableSort: TableSort | undefined = plSortDirection
    ? { columnIndex: 0, direction: plSortDirection }
    : undefined

  function togglePlSort(): void {
    setPlSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
  }

  return (
    <Card padding="none">
      <div className={styles.tableHead}>
        <SectionHead
          title="Packing lists on this container"
          sub={`${packingLists.length} list(s)`}
        />
        {canAdd && (
          <Button
            variant="primary"
            size="sm"
            icon="plus"
            onClick={() => navigate('/packing-lists/new')}
          >
            Add packing list
          </Button>
        )}
      </div>
      <Table
        columns={[
          { title: 'Ref #', sortable: true },
          { title: 'Customer' },
          { title: 'Contact' },
          { title: 'Packages' },
          { title: 'CBM', align: 'right' },
          { title: 'Weight', align: 'right' },
          { title: 'Status' },
          { title: 'Submitted' },
          { title: '', width: '60px' },
        ]}
        rows={sortedPackingLists.map((pl) => ({
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
              {pl.total_weight_kg ? `${Number(pl.total_weight_kg).toFixed(1)} kg` : '—'}
            </Mono>,
            <Badge key="status" variant={PL_STATUS_VARIANT[pl.status]}>
              {pl.status.replace('_', ' ')}
            </Badge>,
            <span key="submitted" className={styles.metaText}>
              {formatDate(pl.created_at, 'short')}
            </span>,
            <ViewLink key="view" onClick={() => navigate(`/packing-lists/${pl.id}`)} />,
          ],
        }))}
        emptyState={<span>No packing lists yet — add one to get started.</span>}
        sort={plTableSort}
        onSort={togglePlSort}
      />
    </Card>
  )
}

/** The tracking tab: the full pipeline and the event log, newest first. */
export function TrackingTab({
  container,
  events,
}: {
  container: Container
  events: ContainerEvent[]
}): JSX.Element {
  const exportEvents = useListExport((format: 'xlsx' | 'csv') => containersApi.exportEvents(container.id, format))
  return (
    <>
      <Card>
        <SectionHead
          title="Tracking timeline"
          sub={`All status events for ${container.container_number}`}
        />
        <div className={styles.stepperSpacer} />
        <ContainerStepper current={container.status} />
      </Card>
      <div className={styles.gridSpacer} />
      <Card padding="none">
        <div className={styles.tableHead}>
          <SectionHead
            title="Event log"
            sub="All tracking events, newest first"
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
            { title: 'Timestamp' },
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
              <Badge key="event" variant={eventBadgeVariant(event.to_status)}>
                {eventLabel(event.from_status, event.to_status)}
              </Badge>,
              <span key="change" className={styles.statusChange}>
                <span className={styles.statusFrom}>
                  {CONTAINER_STATUS_LABELS[event.from_status as ContainerStatus] ??
                    event.from_status}
                </span>
                <span className={styles.statusArrow}>→</span>
                <strong className={styles.statusTo}>
                  {CONTAINER_STATUS_LABELS[event.to_status as ContainerStatus] ?? event.to_status}
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
          emptyState={<span>No tracking events yet.</span>}
        />
      </Card>
    </>
  )
}
