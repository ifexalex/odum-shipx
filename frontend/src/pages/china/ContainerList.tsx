import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { containerKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { containerCapacityCbm, utilizationLevel } from '../../api/containerRules'
import { containersApi, type Container, type ContainerStatus } from '../../api/tracking'
import { Banner, Button, Chip, DateRangeFilter, ExportButton, Icon, ListFooter, Mono, StatCard, StatusBadge, Table, type IconName, type TableRow, Pressable, SearchField, EmptyState, ErrorState } from '../../design/components'
import { useSession } from '../../auth/useSession'
import { useContainerList } from '../../hooks/useContainers'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { useListExport } from '../../hooks/useListExport'
import { type SortableColumn, useTableSort } from '../../hooks/useTableSort'
import styles from './ContainerList.module.css'
import { formatCbm, formatDate, isoDateOffset, todayIso } from '../../lib/format'
import { statusLabel } from '../../design/status'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage, StatRow } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

const SEARCH_DEBOUNCE_MS = 300

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
// Filter chips match the design exactly: All · Active · Packed · In transit · Arrived NG · Cleared
// The four stats a container list shows (FD-18): work waiting at each stage, each a filter.
const STAT_GROUPS: Array<{ label: string; sublabel: string; icon: IconName; statuses: ContainerStatus[] }> = [
  { label: 'Active', sublabel: 'China-side', icon: 'container', statuses: CHINA_ACTIVE },
  { label: 'Packed', sublabel: 'ready to ship', icon: 'package', statuses: CHINA_PACKED },
  { label: 'In transit', sublabel: 'at sea', icon: 'ship', statuses: IN_TRANSIT },
  { label: 'Arrived (NG)', sublabel: 'handed off', icon: 'map', statuses: ARRIVED_NG },
]

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

const ARRIVED_OR_DONE: ContainerStatus[] = ['arrived', 'customs_clearance', 'cleared', 'at_warehouse', 'fully_released', 'cancelled']

function overdueDays(container: Container): number {
  if (!container.estimated_arrival_date || ARRIVED_OR_DONE.includes(container.status)) return 0
  const today = todayIso()
  if (container.estimated_arrival_date >= today) return 0
  const etaMs = Date.parse(`${container.estimated_arrival_date}T00:00:00Z`)
  const todayMs = Date.parse(`${today}T00:00:00Z`)
  return Math.max(1, Math.round((todayMs - etaMs) / 86_400_000))
}

// ETA stays a date after clearance (FD-13): the Status column already says "Cleared", and a word in a date column
// can't be sorted or compared.
function etaColor(container: Container): string {
  if (!container.estimated_arrival_date) return 'var(--color-ink-4)'
  if (CLEARED.includes(container.status)) return 'var(--color-ink-3)'
  if (overdueDays(container) > 0) return 'var(--color-error)'
  if (container.estimated_arrival_date === todayIso()) return 'var(--color-warning)'
  return 'var(--color-ink)'
}

function etaLabel(container: Container): string {
  if (!container.estimated_arrival_date) return '—'
  const dateStr = formatDate(container.estimated_arrival_date, 'short')
  const late = overdueDays(container)
  return late > 0 ? `${dateStr} · ${late}d late` : dateStr
}

/** ISO date (YYYY-MM-DD) for "N days ago" — used as the `created_after` query param. */
function daysAgoIso(days: number): string {
  return isoDateOffset(-days)
}

/** ISO date (YYYY-MM-DD) for "N days from now" — used as the `eta_before` query param. */
function daysFromNowIso(days: number): string {
  return isoDateOffset(days)
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
        <Mono color="var(--color-ink)">{formatCbm(packed)}</Mono>
        {pct != null && <span className={styles.utilPct}>{pct}%</span>}
      </div>
      {pct != null && (
        <div className={styles.utilTrack} title={`${formatCbm(packed)} / ${capacity} CBM`}>
          <div className={[styles.utilFill, fillClass].join(' ')} style={{ width: `${Math.min(pct, 100)}%` }} />
        </div>
      )}
    </div>
  )
}

function containerRow(container: Container, onOpen: () => void): TableRow {
  const plTotal = container.packing_list_count ?? 0
  const plApproved = container.approved_packing_list_count ?? 0

  const originCode = ORIGIN_CODE[container.origin] ?? container.origin
  const destCode = DEST_CODE[container.destination] ?? container.destination

  return {
    onOpen,
    openLabel: `Open container ${container.container_number}`,
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
      <StatusBadge key="status" kind="container" status={container.status} />,
      // Packing lists: "approved / total"
      <Mono key="pls" color={plTotal === 0 ? 'var(--color-ink-4)' : plApproved === plTotal && plTotal > 0 ? 'var(--color-success)' : 'var(--color-ink)'}>
        {plApproved} / {plTotal}
      </Mono>,
      // Utilization — packed CBM + a fill bar (vs capacity) coloured by the
      // absolute-CBM business rule. Bar hidden when capacity is unknown.
      <UtilizationCell key="util" container={container} />,
      <Mono key="eta" color={etaColor(container)}>{etaLabel(container)}</Mono>,
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

  // Debounce the search term; the query hook only refetches once typing settles.
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
  // What the list is showing: the same object drives the query and the Export button, so an export is the rows
  // on screen (every page of them), not a second reading of the filters.
  const listParams = {
    status,
    q: debouncedSearch || undefined,
    created_after: createdRange.createdAfter,
    created_before: createdRange.createdBefore,
    eta_after: etaAfter,
    eta_before: etaBefore,
    ...(sortField ? { sort: sortField, direction: sortDirection } : {}),
  }
  const { items: containers, isLoading, error, hasMore, loadMore, isFetchingMore, totalCount, refetch } = useContainerList(listParams)
  const exportList = useListExport((format: 'xlsx' | 'csv') => containersApi.exportList(listParams, format))

  const canCreate = session?.role === 'china_office_staff'

  // Everyone who can open the list can export it; only China staff create containers (header actions below).

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
    createdRange.clear()
  }

  const chipCount = (statuses: ContainerStatus[]): number => sumStatuses(statuses)

  // Filters applied besides the search, shown on the More filters / Filters button.
  const activeFilters = (activeStatuses ? 1 : 0) + (etaPreset ? 1 : 0) + (createdRange.isActive ? 1 : 0)

  return (
    <ListPage
      header={
        <PageHeader
          title="Containers"
          primary={
            canCreate && (
              <Button variant="primary" icon="plus" onClick={() => navigate('/containers/new')}>
                Create container
              </Button>
            )
          }
          actions={<ExportButton formats={['xlsx', 'csv']} onExport={exportList.onExport} />}
        />
      }
      notices={
        <>
          {error && (
            <ErrorState
              compact
              title="Couldn't load containers"
              error={error}
              onRetry={() => void refetch()}
            />
          )}
          {exportList.error && (
            <Banner
              variant="error"
              title="Couldn't export containers"
              dismissible
              onDismiss={exportList.dismissError}
            >
              {exportList.error}
            </Banner>
          )}
        </>
      }
      // Four numbers worth acting on (FD-18); each applies its filter. "Cleared (30d)" was history, not work.
      stats={
        <StatRow>
          {STAT_GROUPS.map((group) => (
            <StatCard
              key={group.label}
              label={group.label}
              value={sumStatuses(group.statuses)}
              sublabel={group.sublabel}
              icon={group.icon}
              selected={activeStatuses?.join() === group.statuses.join()}
              onSelect={() => selectGroup(group.statuses)}
            />
          ))}
        </StatRow>
      }
      filters={
        <FilterBar
          status={
            <>
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
            </>
          }
          search={
            <SearchField
              label="Search containers"
              placeholder="Container number, vessel name, voyage…"
              value={search}
              onChange={setSearch}
            />
          }
          dateRange={<DateRangeFilter label="Created" range={createdRange} />}
          more={
            <>
              {/* Granular multi-select across all 9 statuses — independent
            entry point from the grouped chips above, same underlying
            `activeStatuses` state (see toggleStatus). */}
              <div className={styles.filtersPanelLabel}>Any status</div>
              <div className={styles.filtersPanelScroll}>
                {ALL_STATUSES.map((s) => {
                  const isChecked = activeStatuses?.includes(s) ?? false
                  return (
                    <Pressable
                      key={s}
                      type="button"
                      role="checkbox"
                      aria-checked={isChecked}
                      className={[
                        styles.filtersPanelItem,
                        isChecked ? styles.filtersPanelItemActive : '',
                      ].join(' ')}
                      onClick={() => toggleStatus(s)}
                    >
                      <span className={styles.checkSlot}>
                        {isChecked && <Icon name="check" size={13} color="var(--color-primary)" />}
                      </span>
                      {statusLabel('container', s)}
                    </Pressable>
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
                  <Pressable
                    key={key}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    className={[
                      styles.filtersPanelItem,
                      isActive ? styles.filtersPanelItemActive : '',
                    ].join(' ')}
                    onClick={() => setEtaPreset(isActive ? null : key)}
                  >
                    <span className={styles.checkSlot}>
                      {isActive && <Icon name="check" size={13} color="var(--color-primary)" />}
                    </span>
                    {ETA_PRESET_LABELS[key]}
                  </Pressable>
                )
              })}
            </>
          }
          activeCount={activeFilters}
          onClear={clearAllFilters}
          label="Filter containers"
        />
      }
      footer={
        <ListFooter
          shown={containers.length}
          total={totalCount}
          hasMore={hasMore}
          loading={isFetchingMore}
          onLoadMore={loadMore}
          noun="containers"
          nounOne="container"
        />
      }
    >
      <Table
        columns={[
          { title: 'Container', type: 'reference', sortable: true },
          { title: 'Vessel · voyage' },
          { title: 'Route' },
          { title: 'Status', type: 'status' },
          { title: 'Packing lists', type: 'number' },
          { title: 'Packed (CBM)', type: 'number' },
          { title: 'ETA', type: 'date', sortable: true },
        ]}
        rows={containers.map((c) => containerRow(c, () => navigate(`/containers/${c.id}`)))}
        loading={isLoading}
        emptyState={
          !isLoading && containers.length === 0 ? (
            activeFilters > 0 || Boolean(debouncedSearch) ? (
              <EmptyState
                compact
                title="No containers match these filters"
                body="Try broadening your status, date, or search criteria."
                action={{ label: 'Clear filters', onClick: clearAllFilters }}
              />
            ) : (
              <EmptyState compact title="No containers yet" body="Create one to get started." />
            )
          ) : undefined
        }
        sort={sort}
        onSort={onSort}
      />
    </ListPage>
  )
}
