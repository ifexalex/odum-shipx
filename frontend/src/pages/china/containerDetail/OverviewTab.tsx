import { type JSX } from 'react'
import { containerCapacityCbm } from '../../../api/containerRules'
import { formatPackageMix } from '../../../api/packingListRules'
import { Avatar, Card, Kvp, Mono, Button } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../ContainerDetail.module.css'
import { formatCbm, formatDate } from '../../../lib/format'
import { utilizationColorClass } from './labels'
import { SummaryTile, EventRow } from './Timeline'
import { type Container, type ContainerEvent } from '../../../api/tracking'
import { type PackingList } from '../../../api/packingList'

/** The overview tab: pipeline, cargo summary and utilization, recent events, top shippers. */
export function OverviewTab({
  container,
  packingLists,
  events,
  onShowTab,
}: {
  container: Container
  packingLists: PackingList[]
  events: ContainerEvent[]
  /** The overview's "View all" links open the tracking and packing-list tabs. */
  onShowTab: (tab: 'packing-lists' | 'tracking') => void
}): JSX.Element {
  const approvedCount = packingLists.filter((pl) => pl.status === 'approved').length

  // Cargo summary aggregates, derived from the container's packing lists.
  const distinctCustomers = new Set(packingLists.map((pl) => pl.customer_id)).size
  // Packages, not item rows: since a manifest row became a bulk quantity, a
  // row count under-reports what is physically in the container (STL409: 81
  // rows vs 437 actual packages).
  const totalCartons = packingLists.reduce(
    (sum, pl) => sum + (pl.package_count ?? pl.carton_count),
    0,
  )
  const containerPackageMix = packingLists.reduce<Record<string, number>>((acc, pl) => {
    for (const [unit, count] of Object.entries(pl.package_mix ?? {})) {
      acc[unit] = (acc[unit] ?? 0) + count
    }
    return acc
  }, {})
  const totalCbm = packingLists.reduce((sum, pl) => sum + Number(pl.total_cbm ?? 0), 0)
  const capacityCbm =
    container.capacity_cbm != null && Number(container.capacity_cbm) > 0
      ? Number(container.capacity_cbm)
      : containerCapacityCbm(container.container_type)
  const recommendedCbm =
    container.recommended_cbm != null && Number(container.recommended_cbm) > 0
      ? Number(container.recommended_cbm)
      : null
  const utilizationPct = capacityCbm ? Math.min((totalCbm / capacityCbm) * 100, 100) : null

  // Group packing lists by customer for the "customers on this container" table.
  const customerGroups = Object.values(
    packingLists.reduce<
      Record<
        string,
        {
          name: string
          phone: string | null
          cartons: number
          cbm: number
          allApproved: boolean
        }
      >
    >((acc, pl) => {
      const key = pl.customer_id
      acc[key] ??= {
        name: pl.customer_name ?? '—',
        phone: pl.customer_phone ?? null,
        cartons: 0,
        cbm: 0,
        allApproved: true,
      }
      acc[key].cartons += pl.package_count ?? pl.carton_count
      acc[key].cbm += Number(pl.total_cbm ?? 0)
      if (pl.status !== 'approved') acc[key].allApproved = false
      return acc
    }, {}),
  ).sort((a, b) => b.cbm - a.cbm)

  // The overview shows only the top shippers by CBM as a compact ranked list —
  // a container can hold 60–100+ customers (STL409 alone has 68), and an
  // uncapped table would bury the rest of the overview. The full per-customer
  // breakdown lives on the Packing lists tab (searchable/sortable).
  const TOP_SHIPPERS_CAP = 5
  const topShippers = customerGroups.slice(0, TOP_SHIPPERS_CAP)
  const hasMoreCustomers = customerGroups.length > TOP_SHIPPERS_CAP

  // Last 5 tracking events, newest first, for the overview.
  const recentEvents = [...events].reverse().slice(0, 5)

  return (
    <>
      <div className={styles.grid2}>
        <Card>
          <SectionHead title="Container info" />
          {/* Number, type, vessel and voyage are in the page header; each fact is stated once (FD-19). Optional facts are
              left out when empty (FD-17). */}
          <Kvp optional label="Seal #" value={container.seal_number && <Mono>{container.seal_number}</Mono>} />
          <Kvp optional label="Shipping line" value={container.shipping_line} />
          <Kvp
            label="Created by"
            value={
              container.created_by_name
                ? `${container.created_by_name} · ${formatDate(container.created_at)}`
                : formatDate(container.created_at)
            }
            divider={false}
          />
        </Card>
        <Card>
          <SectionHead title="Cargo summary" sub="Aggregated from all packing lists" />
          <div className={styles.summaryGrid}>
            <SummaryTile label="Customers" value={distinctCustomers} sub="on this container" />
            <SummaryTile
              label="Packing lists"
              value={`${approvedCount} / ${packingLists.length}`}
              sub="approved"
              accent
            />
            <SummaryTile
              label="Total packages"
              value={totalCartons}
              sub={formatPackageMix(containerPackageMix)}
            />
            <SummaryTile
              label="Total CBM"
              value={formatCbm(totalCbm)}
              sub={capacityCbm ? `of ${capacityCbm} capacity` : 'packed'}
            />
          </div>
          {utilizationPct != null && (
            <div className={styles.utilBox}>
              <div className={styles.utilHead}>
                <span className={styles.utilLabel}>Utilization</span>
                <span className={styles.utilPct}>{utilizationPct.toFixed(1)}%</span>
              </div>
              <div className={styles.utilTrack}>
                <div
                  className={[styles.utilFill, utilizationColorClass(totalCbm)].join(' ')}
                  style={{ width: `${utilizationPct}%` }}
                />
              </div>
              <div className={styles.utilSub}>
                {formatCbm(totalCbm)} of {capacityCbm} CBM packed · room for{' '}
                {formatCbm(Math.max(capacityCbm! - totalCbm, 0))} more
                {recommendedCbm ? ` · recommended ${recommendedCbm} CBM` : ''}
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className={styles.gridSpacer} />
      <div className={styles.grid2}>
        <Card padding="none">
          <div className={styles.tableHead}>
            <SectionHead title="Recent events" sub="Last 5 tracking events" />
            {events.length > 5 && (
              <Button variant="ghost" size="sm" trailingIcon="arrowright" onClick={() => onShowTab('tracking')}>
                View all
              </Button>
            )}
          </div>
          <div className={styles.eventList}>
            {recentEvents.length === 0 ? (
              <div className={styles.eventEmpty}>No tracking events yet.</div>
            ) : (
              recentEvents.map((event, index) => (
                <EventRow key={event.id} event={event} last={index === recentEvents.length - 1} />
              ))
            )}
          </div>
        </Card>

        <Card>
          <div className={styles.tableHead}>
            <SectionHead
              title="Top shippers by CBM"
              sub={`${distinctCustomers} customer${distinctCustomers === 1 ? '' : 's'} on this container`}
            />
            {hasMoreCustomers && (
              <Button variant="ghost" size="sm" trailingIcon="arrowright" onClick={() => onShowTab('packing-lists')}>
                View all
              </Button>
            )}
          </div>
          {topShippers.length === 0 ? (
            <div className={styles.shipperEmpty}>No customers yet.</div>
          ) : (
            <div className={styles.shipperList}>
              {topShippers.map((group) => {
                const share = totalCbm > 0 ? (group.cbm / totalCbm) * 100 : 0
                return (
                  <div key={group.name} className={styles.shipperRow}>
                    <Avatar size={28} name={group.name} roleColor="nigeria" />
                    <div className={styles.shipperBody}>
                      <div className={styles.shipperTop}>
                        <span className={styles.shipperName} title={group.name}>
                          {group.name}
                        </span>
                        <span className={styles.shipperCbm}>
                          <Mono>{formatCbm(group.cbm)}</Mono> CBM
                        </span>
                      </div>
                      <div className={styles.shipperBarRow}>
                        <div className={styles.shipperBarTrack}>
                          <div className={styles.shipperBarFill} style={{ width: `${share}%` }} />
                        </div>
                        <span className={styles.shipperPct}>{share.toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      </div>
    </>
  )
}
