/**
 * Container pipeline — Nigeria-ops dashboard section.
 *
 * Replaces the old horizontal-scrolling kanban (8 columns, each capped at 6
 * cards + "+N more", so most containers were unreachable). A responsive stage
 * rail shows every stage's live count at a glance (no horizontal scroll); the
 * selected stage drives the complete, paginated container table below — so no
 * container is hidden, and the list scales to tens of thousands via load-more.
 */
import { useEffect, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { CONTAINER_STATUS_LABELS } from '../../api/containerRules'
import { type ContainerStats, type ContainerStatus } from '../../api/tracking'
import { useContainerList } from '../../hooks/useContainers'
import { Badge, Button, Card, Chip, Icon, ListFooter, Mono, Table, type BadgeVariant } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './DashboardPipeline.module.css'
import { isoDateOffset, formatDate } from '../../lib/format'

// Pipeline order, loading → fully released (cancelled is not a pipeline stage).
const STAGES: ContainerStatus[] = [
  'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance', 'cleared', 'at_warehouse', 'fully_released',
]
const ACTIVE_STATUS_PARAM = STAGES.join(',')

// Stage accent reuses the app's status semantics (same hues as the status
// badges elsewhere), so a stage reads the same colour everywhere: cool while
// at sea, amber while it needs attention (arrived/customs), green once cleared.
const STAGE_ACCENT: Record<ContainerStatus, string> = {
  loading: 'var(--color-ink-4)',
  sealed: 'var(--color-info)',
  in_transit: 'var(--color-info)',
  arrived: 'var(--color-warning)',
  customs_clearance: 'var(--color-warning)',
  cleared: 'var(--color-primary)',
  at_warehouse: 'var(--color-primary)',
  fully_released: 'var(--color-success)',
  cancelled: 'var(--color-ink-4)',
}

const CONTAINER_BADGE: Record<string, BadgeVariant> = {
  loading: 'neutral',
  sealed: 'info',
  in_transit: 'info',
  arrived: 'warning',
  customs_clearance: 'warning',
  cleared: 'primary',
  at_warehouse: 'primary',
  fully_released: 'success',
  cancelled: 'neutral',
}

type Selected = ContainerStatus | 'all'

// "Arriving" ETA quick-filter — reuses the backend's eta_after/eta_before
// (same contract as the full ContainerList filter panel).
type EtaPreset = '7' | '30' | 'overdue'
const ETA_PRESETS: { key: EtaPreset; label: string }[] = [
  { key: '7', label: '≤ 7 days' },
  { key: '30', label: '≤ 30 days' },
  { key: 'overdue', label: 'Overdue' },
]

function isoOffsetDays(days: number): string {
  return isoDateOffset(days)
}

function etaRange(preset: EtaPreset | null): { eta_after?: string; eta_before?: string } {
  if (preset === null) return {}
  if (preset === 'overdue') return { eta_before: isoOffsetDays(-1) }
  return { eta_after: isoOffsetDays(0), eta_before: isoOffsetDays(Number(preset)) }
}

function etaCell(iso: string | null): string {
  return formatDate(iso)
}

export function ContainerPipeline({ counts }: { counts: ContainerStats | undefined }): JSX.Element {
  const navigate = useNavigate()
  const [selected, setSelected] = useState<Selected>('all')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [etaPreset, setEtaPreset] = useState<EtaPreset | null>(null)

  // Debounce the search box so each keystroke doesn't fire a query.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  // The full, paginated list for the current stage + search + ETA filter —
  // not a 6-card sample. Stage (rail), search (q), and ETA are independent AND
  // filters, so any container is reachable by narrowing, then load-more.
  const { items, hasMore, loadMore, isFetchingMore, isLoading, totalCount } = useContainerList({
    status: selected === 'all' ? ACTIVE_STATUS_PARAM : selected,
    ...(debouncedSearch ? { q: debouncedSearch } : {}),
    ...etaRange(etaPreset),
    limit: 12,
  })

  const activeTotal = counts ? counts.total - counts.cancelled : undefined
  const maxCount = Math.max(1, ...STAGES.map((s) => counts?.[s] ?? 0))

  return (
    <Card padding={20}>
      <SectionHead
        title="Container pipeline"
        sub="Every container by stage — select a stage to see all of them"
        action={<Button variant="secondary" size="sm" onClick={() => navigate('/containers')}>All containers →</Button>}
      />

      <div className={styles.rail}>
        <button
          type="button"
          className={[styles.stage, styles.allStage, selected === 'all' ? styles.stageActive : ''].join(' ')}
          onClick={() => setSelected('all')}
          aria-pressed={selected === 'all'}
        >
          <span className={styles.stageTop}>
            <span className={styles.stageDot} />
            <span className={styles.stageLabel}>All active</span>
          </span>
          <span className={styles.stageCount}>{activeTotal ?? '—'}</span>
          <span className={styles.meterTrack}><span className={styles.meterFill} style={{ width: '100%' }} /></span>
        </button>

        {STAGES.map((stage) => {
          const n = counts?.[stage] ?? 0
          return (
            <button
              key={stage}
              type="button"
              className={[styles.stage, selected === stage ? styles.stageActive : ''].join(' ')}
              style={{ ['--accent' as string]: STAGE_ACCENT[stage] }}
              onClick={() => setSelected(stage)}
              aria-pressed={selected === stage}
            >
              <span className={styles.stageTop}>
                <span className={styles.stageDot} />
                <span className={styles.stageLabel}>{CONTAINER_STATUS_LABELS[stage]}</span>
              </span>
              <span className={styles.stageCount}>{n}</span>
              <span className={styles.meterTrack}>
                <span className={styles.meterFill} style={{ width: `${Math.round((n / maxCount) * 100)}%` }} />
              </span>
            </button>
          )
        })}
      </div>

      <div className={styles.toolbar}>
        <div className={styles.searchWrap}>
          <Icon name="search" size={14} color="var(--color-ink-4)" />
          <input
            className={styles.searchInput}
            placeholder="Search container number or vessel…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search containers"
          />
          {search && (
            <button type="button" className={styles.searchClear} aria-label="Clear search" onClick={() => setSearch('')}>
              <Icon name="x" size={13} color="var(--color-ink-4)" />
            </button>
          )}
        </div>
        <div className={styles.etaChips}>
          <span className={styles.etaLabel}>Arriving</span>
          <Chip active={etaPreset === null} onClick={() => setEtaPreset(null)}>Any</Chip>
          {ETA_PRESETS.map(({ key, label }) => (
            <Chip key={key} active={etaPreset === key} onClick={() => setEtaPreset(etaPreset === key ? null : key)}>
              {label}
            </Chip>
          ))}
        </div>
      </div>

      <div className={styles.tableMeta}>
        <span className={styles.tableTitle}>
          {selected === 'all' ? 'All active containers' : CONTAINER_STATUS_LABELS[selected]}
          {(debouncedSearch || etaPreset) && <span className={styles.filterNote}> · filtered</span>}
        </span>
      </div>

      <Table
        dense
        cardBreakpoint={700}
        columns={[
          { title: 'Container' },
          { title: 'Route' },
          { title: 'Status' },
          { title: 'ETA / Arrival' },
          { title: 'Packing lists', align: 'right' },
          { title: '', width: '64px' },
        ]}
        rows={items.map((c) => ({
          cells: [
            <div key="num">
              <Mono>{c.container_number}</Mono>
              {c.vessel_name && <div className={styles.subCell}>{c.vessel_name}</div>}
            </div>,
            <span key="route" className={styles.subCell} style={{ marginTop: 0 }}>
              {c.origin} → {c.destination}
            </span>,
            <Badge key="status" variant={CONTAINER_BADGE[c.status] ?? 'neutral'}>
              {CONTAINER_STATUS_LABELS[c.status] ?? c.status}
            </Badge>,
            <span key="eta" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
              {c.status === 'arrived' || c.status === 'customs_clearance' || c.status === 'cleared' || c.status === 'at_warehouse' || c.status === 'fully_released'
                ? etaCell(c.actual_arrival_date ?? c.estimated_arrival_date)
                : etaCell(c.estimated_arrival_date)}
            </span>,
            <Mono key="pl">{c.packing_list_count ?? 0}</Mono>,
            <Button key="view" variant="ghost" size="sm" onClick={() => navigate(`/containers/${c.id}`)}>View</Button>,
          ],
        }))}
        loading={isLoading}
        emptyState={
          !isLoading ? (
            <span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>
              {debouncedSearch || etaPreset
                ? 'No containers match your search and filters.'
                : `No containers in ${selected === 'all' ? 'the pipeline' : CONTAINER_STATUS_LABELS[selected]}.`}
            </span>
          ) : undefined
        }
      />

      <ListFooter
        shown={items.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="containers"
      />
    </Card>
  )
}
