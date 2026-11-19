/**
 * Tenant-admin Activity Log — the full audit trail, not just the 8-row
 * `ActivityFeed` dashboard widget.
 *
 * Ground-truth gap found live, reported directly by the user: "we need to
 * ensure that we have log trail for everything, since it has to do with
 * people's goods and money, so that the tenant admin can see every activity
 * going on." The only thing that existed was a small dashboard widget with
 * no filtering and no way to see *what* changed (before/after state) — a
 * tenant admin genuinely could not audit a specific payment, refund, or
 * status change, only see that "something happened." Modelled closely on
 * `platform/PlatformAuditLog.tsx` (which already had this shape for
 * platform-level actions).
 *
 * Follow-up (2026-09-07): the first version's single "Record type" dropdown
 * wasn't real filtering for a money/goods audit trail — no way to narrow by
 * date, by who did it, by what kind of action, or to find every action on
 * one specific record. Added: a Category grouping (so "Money" or "Goods &
 * shipments" narrows the Record-type options for easy filtering, per the
 * report), an Action filter, a search box (actor name or a pasted record
 * id), a date range, and a sort-order toggle — all combine as one query,
 * confirmed against the real backend (`AND`, never a silent `OR` that would
 * widen the result set the admin thinks they're looking at).
 *
 * Second follow-up, same day: "Details" used to append the before/after
 * diff as a block *after the entire table* — clicking it on any row but the
 * last meant scrolling well past the rest of the list to see it, and the
 * diff moved every time a different row was expanded. Now a modal, so it
 * opens in the same place regardless of which row was clicked and never
 * disturbs the table's scroll position.
 */
import { useCallback, useEffect, useRef, useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configApi, type TenantActivityEntry } from '../../api/tenantManagement'
import {
  Badge,
  Banner,
  Button,
  Card,
  Chip,
  DateRangeFilter,
  Icon,
  ListFooter,
  Modal,
  Mono,
  Table,
  type BadgeVariant,
} from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './admin.module.css'
import { isoDateOffset, formatDateTime } from '../../lib/format'

// Every entity_type actually written by shared.audit.log_audit(...) across
// the backend, grouped into the categories a tenant admin actually thinks
// in — "show me every money-related thing" is a real, common audit
// question; "show me every audit_log row" is not.
const CATEGORIES: { label: string; entityTypes: string[] }[] = [
  {
    label: 'Money',
    entityTypes: ['billing', 'payment_claim', 'payment_record', 'refund_request', 'misc_charge', 'carryover_ledger', 'charge_type'],
  },
  {
    label: 'Goods & shipments',
    entityTypes: ['container', 'container_document', 'packing_list', 'manifest', 'damage_claim', 'missing_item', 'seized_item', 'pickup_record', 'release_note', 'cbm_dispute'],
  },
  {
    label: 'Customers',
    entityTypes: ['customer', 'customer_invite'],
  },
  {
    // impersonation_session deliberately excluded — reported directly by
    // the user as irrelevant to filter by here: it's a platform-admin
    // action performed *on* this tenant, not something staff do, and isn't
    // a business record like the rest of this category. It's still written
    // to this tenant's audit_log (and still reachable with no category/type
    // filter selected) — just not offered as a Record-type option.
    label: 'Staff & access',
    entityTypes: ['tenant_user'],
  },
  {
    label: 'Settings',
    entityTypes: ['tenant', 'tenant_config', 'warehouse', 'notification_template'],
  },
  {
    label: 'System',
    entityTypes: ['notification_log', 'sla_breach'],
  },
]
const ALL_ENTITY_TYPES = CATEGORIES.flatMap((c) => c.entityTypes)

const ACTIONS: TenantActivityEntry['action'][] = ['CREATE', 'UPDATE', 'STATUS_CHANGE', 'DELETE']

function humanEntity(entityType: string): string {
  return entityType.replace(/_/g, ' ')
}

function actionVariant(action: TenantActivityEntry['action']): BadgeVariant {
  if (action === 'DELETE') return 'error'
  if (action === 'STATUS_CHANGE') return 'warning'
  if (action === 'CREATE') return 'success'
  return 'info'
}

export function ActivityLog(): JSX.Element {
  const [entries, setEntries] = useState<TenantActivityEntry[]>([])
  const [category, setCategory] = useState('')
  const [entityFilter, setEntityFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [daysBack, setDaysBack] = useState<number | null>(null)
  // Exact custom range — reported directly by the user: presets alone
  // ("last 7/30/90 days") aren't "fully functional" date filtering; an
  // audit trail needs an exact from/to range too (e.g. "everything on the
  // day of that disputed charge"). Take precedence over the preset once set.
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  // Resolved when the preset is chosen, not during render: Date.now() is impure,
  // and recomputing it per render let the window slide forward while the page
  // sat open, so two loads with the same preset could query different ranges.
  const [presetFrom, setPresetFrom] = useState<string | undefined>(undefined)
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [cursor, setCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Debounce the search box — searching on every keystroke would fire a
  // request per character for what is effectively a live audit query.
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 350)
    return () => clearTimeout(t)
  }, [searchInput])

  // Selecting a category narrows Record-type's options; switching category
  // clears a Record-type selection that no longer belongs to it.
  const activeCategory = CATEGORIES.find((c) => c.label === category)
  const entityOptions = activeCategory ? activeCategory.entityTypes : ALL_ENTITY_TYPES
  // Derived, not corrected by an effect: a Record-type selection that no longer
  // belongs to the chosen category is simply not in effect. The old effect
  // cleared it one render late, so the first render after switching category
  // still queried with the stale entity type.
  const effectiveEntityFilter = entityFilter && entityOptions.includes(entityFilter) ? entityFilter : ''

  // An explicit custom date always wins over the "last N days" preset —
  // picking one clears the other so the two controls never silently fight.
  const createdAfter = dateFrom || presetFrom
  const createdBefore = dateTo || undefined

  function handlePreset(days: number | null): void {
    setDaysBack(days)
    setPresetFrom(days ? isoDateOffset(-days) : undefined)
    setDateFrom('')
    setDateTo('')
  }
  function handleCustomFrom(value: string): void {
    setDateFrom(value)
    setDaysBack(null)
    setPresetFrom(undefined)
  }
  function handleCustomTo(value: string): void {
    setDateTo(value)
    setDaysBack(null)
    setPresetFrom(undefined)
  }

  const load = useCallback(
    async (nextCursor?: string) => {
      setLoading(true)
      setError(null)
      try {
        // Resolved here from `category` rather than closing over the
        // `activeCategory` object: every dependency below is then a primitive,
        // which is what lets the compiler preserve this memoization.
        const cat = CATEGORIES.find((c) => c.label === category)
        const entityTypes = effectiveEntityFilter ? [effectiveEntityFilter] : cat ? cat.entityTypes : undefined
        const result = await configApi.activity({
          entityTypes,
          action: actionFilter || undefined,
          q: search || undefined,
          createdAfter,
          createdBefore,
          sort: sortDirection,
          limit: 50,
          cursor: nextCursor,
        })
        setEntries((prev) => (nextCursor ? [...prev, ...result.data] : result.data))
        setCursor(result.meta.pagination.next_cursor)
        setHasMore(result.meta.pagination.has_more)
        setTotalCount(result.meta.pagination.total_count)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load the activity log.')
      } finally {
        setLoading(false)
      }
    },
    [effectiveEntityFilter, category, actionFilter, search, createdAfter, createdBefore, sortDirection],
  )

  const loadRef = useRef(load)
  // Assigned after commit, not during render — see useIdleTimeout.
  useEffect(() => {
    loadRef.current = load
  })
  useEffect(() => {
    void loadRef.current()
  }, [effectiveEntityFilter, category, actionFilter, search, createdAfter, createdBefore, sortDirection])

  const expandedEntry = entries.find((e) => e.id === expandedId) ?? null
  const filtersActive = !!(category || actionFilter || search || daysBack || dateFrom || dateTo)

  function clearFilters(): void {
    setCategory('')
    setEntityFilter('')
    setActionFilter('')
    setSearchInput('')
    setSearch('')
    setDaysBack(null)
    setPresetFrom(undefined)
    setDateFrom('')
    setDateTo('')
  }

  useTopBarSlot({ subtitle: 'Every recorded change in your account — who did what, and when. Confirmed/rejected payments, refunds, and claims all show exactly what changed, not just that something did.' })

  return (
    <div>

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Couldn't load">{error}</Banner></div>}

      <Card padding="default" style={{ marginBottom: 'var(--space-4)' }}>
        {/* Row 1 — primary dimension as chips + search, matching every other
            tenant-admin list page (Customers / Users / Billing). */}
        <div className={styles.filterRow}>
          <div className={styles.chips}>
            <Chip active={category === ''} onClick={() => setCategory('')}>
              All
            </Chip>
            {CATEGORIES.map((c) => (
              <Chip
                key={c.label}
                active={category === c.label}
                onClick={() => setCategory(category === c.label ? '' : c.label)}
              >
                {c.label}
              </Chip>
            ))}
          </div>
          <div className={styles.searchWrap}>
            <Icon name="search" size={14} color="var(--color-ink-4)" />
            <input
              className={styles.searchInput}
              aria-label="Search"
              placeholder="Person's name, or paste a record id…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
        </div>

        {/* Row 2 — secondary controls, all on the same 36px baseline. */}
        <div className={styles.filterControls}>
          <div className={styles.controlGroup}>
            <label htmlFor="activity_entity_type" className={styles.controlLabel}>Record type</label>
            <select
              id="activity_entity_type"
              className={styles.control}
              style={{ textTransform: 'capitalize' }}
              value={effectiveEntityFilter}
              onChange={(e) => setEntityFilter(e.target.value)}
            >
              <option value="">{activeCategory ? `All in ${activeCategory.label}` : 'All types'}</option>
              {entityOptions.map((t) => (
                <option key={t} value={t} style={{ textTransform: 'capitalize' }}>{humanEntity(t)}</option>
              ))}
            </select>
          </div>

          <div className={styles.controlGroup}>
            <label htmlFor="activity_action" className={styles.controlLabel}>Action</label>
            <select
              id="activity_action"
              className={styles.control}
              style={{ textTransform: 'capitalize' }}
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
            >
              <option value="">All actions</option>
              {ACTIONS.map((a) => (
                <option key={a} value={a} style={{ textTransform: 'capitalize' }}>{a.replace(/_/g, ' ').toLowerCase()}</option>
              ))}
            </select>
          </div>

          <div className={styles.controlGroup}>
            <span className={styles.controlLabel}>When</span>
            <DateRangeFilter value={daysBack} onChange={handlePreset} />
          </div>

          <div className={styles.controlGroup}>
            <span className={styles.controlLabel}>From</span>
            <input
              type="date"
              className={styles.control}
              aria-label="From (custom)"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => handleCustomFrom(e.target.value)}
            />
          </div>

          <div className={styles.controlGroup}>
            <span className={styles.controlLabel}>To</span>
            <input
              type="date"
              className={styles.control}
              aria-label="To (custom)"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => handleCustomTo(e.target.value)}
            />
          </div>

          <div className={styles.controlGroup}>
            <label htmlFor="activity_sort" className={styles.controlLabel}>Sort</label>
            <select
              id="activity_sort"
              className={styles.control}
              value={sortDirection}
              onChange={(e) => setSortDirection(e.target.value as 'asc' | 'desc')}
            >
              <option value="desc">Newest first</option>
              <option value="asc">Oldest first</option>
            </select>
          </div>

          {filtersActive && (
            <Button variant="ghost" onClick={clearFilters}>Clear filters</Button>
          )}
        </div>
      </Card>

      <Card padding="none">
        <Table
          columns={[
            { title: 'Timestamp' },
            { title: 'Record' },
            { title: 'Action' },
            { title: 'By' },
            { title: '', width: '90px' },
          ]}
          rows={entries.map((e) => ({
            cells: [
              <Mono key="ts">{formatDateTime(e.created_at, { year: false })}</Mono>,
              <span key="entity" style={{ fontSize: 'var(--text-sm)', textTransform: 'capitalize' }}>{humanEntity(e.entity_type)}</span>,
              <Badge key="action" variant={actionVariant(e.action)}>{e.action.replace(/_/g, ' ')}</Badge>,
              <span key="actor" style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>{e.actor_name ?? (e.actor_id ? e.actor_id.slice(0, 8) : 'System')}</span>,
              (e.before_state || e.after_state) ? (
                <Button
                  key="details"
                  variant="ghost"
                  size="sm"
                  onClick={() => setExpandedId(e.id)}
                >
                  Details
                </Button>
              ) : (
                <span key="details" />
              ),
            ],
          }))}
          emptyState={
            <span style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>
              {loading ? 'Loading activity…' : 'No activity matches these filters.'}
            </span>
          }
        />
      </Card>

      <Modal
        open={!!expandedEntry}
        onClose={() => setExpandedId(null)}
        title={expandedEntry ? `${humanEntity(expandedEntry.entity_type)} — ${expandedEntry.action.replace(/_/g, ' ')}` : undefined}
        width={720}
      >
        {expandedEntry && (
          <>
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', marginBottom: 'var(--space-4)' }}>
              {formatDateTime(expandedEntry.created_at)}
              {' · by '}
              {expandedEntry.actor_name ?? (expandedEntry.actor_id ? expandedEntry.actor_id.slice(0, 8) : 'System')}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-4)' }}>
              <div>
                <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--color-ink-4)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', marginBottom: 'var(--space-2)' }}>
                  Before
                </div>
                <pre style={{ margin: 0, fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', overflowX: 'auto', background: 'var(--color-page)', padding: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}>
                  {JSON.stringify(expandedEntry.before_state ?? {}, null, 2)}
                </pre>
              </div>
              <div>
                <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--color-ink-4)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', marginBottom: 'var(--space-2)' }}>
                  After
                </div>
                <pre style={{ margin: 0, fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', overflowX: 'auto', background: 'var(--color-page)', padding: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}>
                  {JSON.stringify(expandedEntry.after_state ?? {}, null, 2)}
                </pre>
              </div>
            </div>
          </>
        )}
      </Modal>

      <ListFooter
        shown={entries.length}
        total={totalCount}
        hasMore={hasMore}
        loading={loading}
        onLoadMore={() => void load(cursor ?? undefined)}
        noun="log entries"
      />
    </div>
  )
}
