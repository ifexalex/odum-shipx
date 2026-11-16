import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { containerKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { CONTAINER_STATUS_LABELS, containerCapacityCbm, utilizationLevel } from '../../api/containerRules'
import { containersApi, type Container, type ContainerStatus } from '../../api/tracking'
import { Badge, Banner, Button, Card, Chip, DateRangeFilter, Icon, KebabBtn, Mono, StatCard, Table, ListFooter, type TableRow } from '../../design/components'
import { useSession } from '../../auth/useSession'
import { useContainerList } from '../../hooks/useContainers'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { type SortableColumn, useTableSort } from '../../hooks/useTableSort'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './ContainerList.module.css'

const SEARCH_DEBOUNCE_MS = 300
const DAY_MS = 24 * 60 * 60 * 1000

// 'Container' (container_number, text) defaults asc; 'ETA' is a forward-looking
// scheduling date (not a "created at" timestamp) so it defaults asc too —
// soonest-arriving container first is the operationally useful default for
// China-side ops. See BillingList/ClaimList for the created/billed/filed-desc
// convention those "when was this recorded" columns follow instead.
const SORT_COLUMNS: SortableColumn[] = [
  { index: 0, field: 'container_number', defaultDirection: 'asc' },
  { index: 6, field: 'estimated_arrival_date', defaultDirection: 'asc' },
]

// All 9 real container statuses (services/tracking/service.py's _NEXT_STATE +
// terminal 'cancelled') — the Filters panel's granular multi-select, distinct
// from the grouped quick-access chips above the table (CHIP_FILTERS).
const ALL_STATUSES: ContainerStatus[] = [
  'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance',
  'cleared', 'at_warehouse', 'fully_released', 'cancelled',
]

type EtaPresetKey = '7' | '30' | '90' | 'overdue'

const ETA_PRESET_LABELS: Record<EtaPresetKey, string> = {
  '7': 'Arriving in 7 days',
  '30': 'Arriving in 30 days',
  '90': 'Arriving in 90 days',
  overdue: 'Overdue (past ETA)',
}
const ETA_PRESET_KEYS: EtaPresetKey[] = ['7', '30', '90', 'overdue']

// Status groups matching the design spec's filter chips
const CHINA_ACTIVE: ContainerStatus[] = ['loading']
const CHINA_PACKED: ContainerStatus[] = ['sealed']
const IN_TRANSIT: ContainerStatus[] = ['in_transit']
const ARRIVED_NG: ContainerStatus[] = ['arrived', 'customs_clearance']
const CLEARED: ContainerStatus[] = ['cleared', 'at_warehouse', 'fully_released']
const CHINA_SIDE: ContainerStatus[] = [...CHINA_ACTIVE, ...CHINA_PACKED]

// Filter chips match the design exactly: All · Active · Packed · In transit · Arrived NG · Cleared
const CHIP_FILTERS: Array<{ label: string; statuses: ContainerStatus[] }> = [
  { label: 'Active', statuses: CHINA_ACTIVE },
  { label: 'Packed', statuses: CHINA_PACKED },
  { label: 'In transit', statuses: IN_TRANSIT },
  { label: 'Arrived NG', statuses: ARRIVED_NG },
  { label: 'Cleared', statuses: CLEARED },
]

// Maps city names → IATA-style port codes shown in the route cell.
// Falls back to the raw string when no mapping is found.
const ORIGIN_CODE: Record<string, string> = {
  Guangzhou: 'CN-CAN', Shanghai: 'CN-SHA', Shenzhen: 'CN-SZX', Ningbo: 'CN-NGB',
  Beijing: 'CN-BJS', Tianjin: 'CN-TSN', Qingdao: 'CN-TAO', China: 'CN',
}
const DEST_CODE: Record<string, string> = {
  Lagos: 'NG-LOS', Abuja: 'NG-ABV', 'Port Harcourt': 'NG-PHC', Nigeria: 'NG',
}

function statusBadgeVariant(status: ContainerStatus): 'warning' | 'info' | 'success' {
  if (CLEARED.includes(status)) return 'success'
  if (CHINA_SIDE.includes(status)) return 'warning'
  if (ARRIVED_NG.includes(status)) return 'warning'
  return 'info'
}

function etaColor(container: Container): string {
  if (CLEARED.includes(container.status)) return 'var(--color-success)'
  if (!container.estimated_arrival_date) return 'var(--color-ink-4)'
  if (container.estimated_arrival_date === new Date().toISOString().slice(0, 10)) return 'var(--color-warning)'
  return 'var(--color-ink)'
}

function etaLabel(container: Container): string {
  if (CLEARED.includes(container.status)) return 'Cleared'
  return container.estimated_arrival_date ?? '—'
}

/** ISO date (YYYY-MM-DD) for "N days ago" — used as the `created_after` query param. */
function daysAgoIso(days: number): string {
  return new Date(Date.now() - days * DAY_MS).toISOString().slice(0, 10)
}

/** ISO date (YYYY-MM-DD) for "N days from now" — used as the `eta_before` query param. */
function daysFromNowIso(days: number): string {
  return new Date(Date.now() + days * DAY_MS).toISOString().slice(0, 10)
}

/** Maps an "Arriving" preset to the `eta_after`/`eta_before` query params. */
function etaRangeFor(preset: EtaPresetKey | null): { etaAfter?: string; etaBefore?: string } {
  if (preset === null) return {}
  if (preset === 'overdue') return { etaBefore: daysAgoIso(1) }
  return { etaAfter: daysAgoIso(0), etaBefore: daysFromNowIso(Number(preset)) }
}

const UTIL_FILL_CLASS: Record<ReturnType<typeof utilizationLevel>, string> = {
  green: styles.utilGreen!,
  yellow: styles.utilYellow!,
  red: styles.utilRed!,
}

// Packed CBM + a capacity fill bar. The bar's width is packed/capacity (visual
// fullness); its colour is the business "well-loaded" signal (absolute CBM, so
// a green bar means an economically-loaded container, not simply a full one).
function UtilizationCell({ container }: { container: Container }): JSX.Element {
  const packed = container.total_cbm_packed != null ? Number(container.total_cbm_packed) : null
  if (packed == null || packed <= 0) {
    return <span className={styles.dimText}>—</span>
  }
  const capacity = container.capacity_cbm != null ? Number(container.capacity_cbm) : containerCapacityCbm(container.container_type)
  const pct = capacity && capacity > 0 ? Math.round((packed / capacity) * 100) : null
  const fillClass = UTIL_FILL_CLASS[utilizationLevel(packed)]
  return (
    <div className={styles.utilCell}>
      <div className={styles.utilTop}>
        <Mono color="var(--color-ink)">{packed.toFixed(1)}</Mono>
        {pct != null && <span className={styles.utilPct}>{pct}%</span>}
      </div>
      {pct != null && (
        <div className={styles.utilTrack} title={`${packed.toFixed(1)} / ${capacity} CBM`}>
          <div className={[styles.utilFill, fillClass].join(' ')} style={{ width: `${Math.min(pct, 100)}%` }} />
        </div>
      )}
    </div>
  )
}

function containerRow(container: Container, onView: () => void): TableRow {
  const plTotal = container.packing_list_count ?? 0
  const plApproved = container.approved_packing_list_count ?? 0

  const originCode = ORIGIN_CODE[container.origin] ?? container.origin
  const destCode = DEST_CODE[container.destination] ?? container.destination

  return {
    cells: [
      <Mono key="num" color="var(--color-ink)">{container.container_number}</Mono>,
      // Vessel · voyage — two-line cell
      container.vessel_name ? (
        <div key="vessel" className={styles.vesselCell}>
          <div className={styles.vesselName}>{container.vessel_name}</div>
          {container.voyage_number && (
            <div className={styles.vesselVoy}>Voy {container.voyage_number}</div>
          )}
        </div>
      ) : <span key="vessel" className={styles.dimText}>—</span>,
      <span key="route" className={styles.routeCell}>
        <Mono color="var(--color-info)">{originCode}</Mono>
        <Icon name="arrowright" size={10} color="var(--color-ink-4)" />
        <Mono color="var(--color-accent)">{destCode}</Mono>
      </span>,
      <Badge key="status" variant={statusBadgeVariant(container.status)}>
        {CONTAINER_STATUS_LABELS[container.status]}
      </Badge>,
      // Packing lists: "approved / total"
      <Mono key="pls" color={plTotal === 0 ? 'var(--color-ink-4)' : plApproved === plTotal && plTotal > 0 ? 'var(--color-success)' : 'var(--color-ink)'}>
        {plApproved} / {plTotal}
      </Mono>,
      // Utilization — packed CBM + a fill bar (vs capacity) coloured by the
      // absolute-CBM business rule. Bar hidden when capacity is unknown.
      <UtilizationCell key="util" container={container} />,
      <Mono key="eta" color={etaColor(container)}>{etaLabel(container)}</Mono>,
      <KebabBtn key="actions" label={`Open ${container.container_number}`} onClick={onView} />,
    ],
  }
}

export function ContainerList(): JSX.Element {
  const { session } = useSession()
  const navigate = useNavigate()
  const [activeStatuses, setActiveStatuses] = useState<ContainerStatus[] | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  // Opt-in "created within" filter shared by the quick calendar button and the
  // Filters panel's custom From/To — null/'' means no date filter (show
  // everything), and must stay that way by default: this dev tenant alone
  // has 200+ containers, so a "helpful" default date scope would silently
  // hide most of them. An explicit custom date always wins over the preset.
  const createdRange = useDateRangeFilter()
  // "Arriving" (ETA range) — lives only in the Filters panel, distinct from
  // the standalone date button above which filters on `created_at`.
  const [etaPreset, setEtaPreset] = useState<EtaPresetKey | null>(null)
  const [filtersOpen, setFiltersOpen] = useState(false)

  // Debounce the search term (table search box and header search box both
  // write to `search`); the query hook only refetches once typing settles.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search])

  // Broad fetch for stat counts — served from cache after first load
  // Tenant-wide per-status counts — SQL-computed server-side (GET
  // /v1/containers/stats) so the figures stay correct as containers grow to
  // tens of thousands, instead of counting a capped fetched sample. Group
  // totals (Active, Cleared, …) are summed here from the per-status counts.
  const { data: statsRaw } = useQuery({
    queryKey: containerKeys.stats(),
    queryFn: () => containersApi.stats(),
    staleTime: STALE_5_MIN,
  })

  const sumStatuses = useCallback(
    (statuses: ContainerStatus[]): number =>
      statuses.reduce((n, k) => n + (statsRaw?.[k] ?? 0), 0),
    [statsRaw],
  )

  const stats = useMemo(() => ({
    active:    sumStatuses(CHINA_ACTIVE),
    packed:    sumStatuses(CHINA_PACKED),
    inTransit: sumStatuses(IN_TRANSIT),
    arrivedNg: sumStatuses(ARRIVED_NG),
    // "(30d)" — cleared/at_warehouse/fully_released created in the last 30 days.
    cleared:   statsRaw?.cleared_30d ?? 0,
    total:     statsRaw?.total ?? 0,
  }), [statsRaw, sumStatuses])

  // Paginated table — cursor pagination via useContainerList
  //
  // Ground-truth fix: this used to send only `activeStatuses[0]` — grouped
  // chips like "Cleared" (cleared + at_warehouse + fully_released) silently
  // fetched just the first status in the group. Now that the backend accepts
  // a comma-separated status list (repository.list_containers's
  // `status = ANY(%(statuses)s)`), send the full set.
  const status = activeStatuses?.length ? activeStatuses.join(',') : undefined
  const { etaAfter, etaBefore } = etaRangeFor(etaPreset)
  const { sort, onSort, sortField, sortDirection } = useTableSort(SORT_COLUMNS)
  const { items: containers, isLoading, error, hasMore, loadMore, isFetchingMore, totalCount } =
    useContainerList({
      status,
      q: debouncedSearch || undefined,
      created_after: createdRange.createdAfter,
      created_before: createdRange.createdBefore,
      eta_after: etaAfter,
      eta_before: etaBefore,
      ...(sortField ? { sort: sortField, direction: sortDirection } : {}),
    })

  const canCreate = session?.role === 'china_office_staff'

  // Inject action buttons + a search handler into the shared TopBar (prototype:
  // actions sit between the search box and the bell, not in the page body).
  // The header search box shares `search` state with the table's own search
  // input below, rather than running an independent search implementation.
  useTopBarSlot({
    actions: canCreate ? (
      <>
        <Button variant="secondary" icon="download">Export</Button>
        <Button variant="primary" icon="plus" onClick={() => navigate('/containers/new')}>
          Create container
        </Button>
      </>
    ) : null,
    onSearch: setSearch,
    searchPlaceholder: 'Search containers…',
  })

  function selectGroup(statuses: ContainerStatus[]): void {
    const alreadyActive = activeStatuses?.join() === statuses.join()
    setActiveStatuses(alreadyActive ? null : statuses)
  }

  // Filters panel's granular multi-select — toggling any individual status
  // overwrites `activeStatuses` (shared with the top chips), so the two entry
  // points can never silently AND together: there is exactly one active
  // status-filter value, and picking here visually clears whichever chip
  // group was previously highlighted (its exact array no longer matches).
  function toggleStatus(status: ContainerStatus): void {
    const current = activeStatuses ?? []
    const next = current.includes(status) ? current.filter((s) => s !== status) : [...current, status]
    setActiveStatuses(next.length ? next : null)
  }

  // Note: does NOT reset the "Created" date range — that's the standalone
  // date button's state, which lives outside the Filters panel entirely.
  function clearAllFilters(): void {
    setActiveStatuses(null)
    setSearch('')
    setEtaPreset(null)
    setFiltersOpen(false)
  }

  const chipCount = (statuses: ContainerStatus[]): number => sumStatuses(statuses)

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load containers">{error.message}</Banner>
        </div>
      )}

      {/* Stats row — matches design exactly: Active · Packed · In transit · Arrived (NG) · Cleared */}
      <div className={styles.statsRow}>
        <StatCard label="Active"       value={stats.active}    sublabel="China-side"   icon="container" />
        <StatCard label="Packed"       value={stats.packed}    sublabel="ready to ship" icon="package" />
        <StatCard label="In transit"   value={stats.inTransit} sublabel="at sea"        icon="ship" />
        <StatCard label="Arrived (NG)" value={stats.arrivedNg} sublabel="handed off"    icon="map" />
        <StatCard label="Cleared (30d)" value={stats.cleared}  sublabel="released"      icon="check" />
      </div>

      {/* Filter bar */}
      <Card padding={16}>
        <div className={styles.filterRow}>
          <div className={styles.chips}>
            <Chip active={activeStatuses === null} onClick={() => setActiveStatuses(null)}>
              All{stats.total > 0 && <span className={styles.chipCount}>{stats.total}</span>}
            </Chip>
            {CHIP_FILTERS.map((group) => (
              <Chip
                key={group.label}
                active={activeStatuses?.join() === group.statuses.join()}
                onClick={() => selectGroup(group.statuses)}
              >
                {group.label}
                {statsRaw && (
                  <span className={styles.chipCount}>{chipCount(group.statuses)}</span>
                )}
              </Chip>
            ))}
          </div>

          <div className={styles.searchWrap}>
            <Icon name="search" size={14} color="var(--color-ink-4)" />
            <input
              className={styles.searchInput}
              placeholder="Container number, vessel name, voyage…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>

          <DateRangeFilter value={createdRange.daysBack} onChange={createdRange.handlePreset} />

          <div className={styles.customDateWrap}>
            <label htmlFor="container_created_from" className={styles.customDateLabel}>From</label>
            <input
              id="container_created_from"
              type="date"
              className={styles.customDateInput}
              value={createdRange.dateFrom}
              max={createdRange.dateTo || undefined}
              onChange={(e) => createdRange.handleCustomFrom(e.target.value)}
            />
            <label htmlFor="container_created_to" className={styles.customDateLabel}>To</label>
            <input
              id="container_created_to"
              type="date"
              className={styles.customDateInput}
              value={createdRange.dateTo}
              min={createdRange.dateFrom || undefined}
              onChange={(e) => createdRange.handleCustomTo(e.target.value)}
            />
          </div>

          <div className={styles.filtersWrap}>
            <Button variant="secondary" icon="filter" onClick={() => setFiltersOpen((o) => !o)}>
              Filters
            </Button>
            {filtersOpen && (
              <>
                <div className={styles.filtersOverlay} onClick={() => setFiltersOpen(false)} />
                <div className={styles.filtersPanel} role="dialog" aria-label="Filters">
                  <div className={styles.filtersPanelHeader}>Filters</div>

                  {/* Granular multi-select across all 9 statuses — independent
                      entry point from the grouped chips above, same underlying
                      `activeStatuses` state (see toggleStatus). */}
                  <div className={styles.filtersPanelLabel}>Status</div>
                  <div className={styles.filtersPanelScroll}>
                    {ALL_STATUSES.map((s) => {
                      const isChecked = activeStatuses?.includes(s) ?? false
                      return (
                        <button
                          key={s}
                          type="button"
                          role="checkbox"
                          aria-checked={isChecked}
                          className={[styles.filtersPanelItem, isChecked ? styles.filtersPanelItemActive : ''].join(' ')}
                          onClick={() => toggleStatus(s)}
                        >
                          <span className={styles.checkSlot}>
                            {isChecked && <Icon name="check" size={13} color="var(--color-primary)" />}
                          </span>
                          {CONTAINER_STATUS_LABELS[s]}
                        </button>
                      )
                    })}
                  </div>

                  {/* ETA range — distinct from the standalone "date created"
                      button, which stays outside this panel and is untouched
                      by Clear all filters below. */}
                  <div className={styles.filtersPanelLabel}>Arriving</div>
                  {ETA_PRESET_KEYS.map((key) => {
                    const isActive = etaPreset === key
                    return (
                      <button
                        key={key}
                        type="button"
                        role="option"
                        aria-selected={isActive}
                        className={[styles.filtersPanelItem, isActive ? styles.filtersPanelItemActive : ''].join(' ')}
                        onClick={() => setEtaPreset(isActive ? null : key)}
                      >
                        <span className={styles.checkSlot}>
                          {isActive && <Icon name="check" size={13} color="var(--color-primary)" />}
                        </span>
                        {ETA_PRESET_LABELS[key]}
                      </button>
                    )
                  })}

                  <button type="button" className={styles.filtersPanelClear} onClick={clearAllFilters}>
                    Clear all filters
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding={0}>
          <Table
            columns={[
              { title: 'Container', sortable: true },
              { title: 'Vessel · voyage' },
              { title: 'Route' },
              { title: 'Status' },
              { title: 'Packing lists', align: 'right' },
              { title: 'Utilization' },
              { title: 'ETA', sortable: true },
              { title: '', width: '40px' },
            ]}
            rows={containers.map((c) => containerRow(c, () => navigate(`/containers/${c.id}`)))}
            loading={isLoading}
            emptyState={!isLoading && containers.length === 0 ? <span>No containers yet — create one to get started.</span> : undefined}
            sort={sort}
            onSort={onSort}
          />
        </Card>
        <ListFooter
        shown={containers.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="containers"
      />
      </div>
    </div>
  )
}
