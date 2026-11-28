/**
 * 14.7 — Platform Audit Log (Section 14 of the prototype, reports-screens.jsx).
 *
 * Cross-tenant audit trail: tenant lifecycle events, impersonation sessions,
 * settings changes. Filters by tenant and action; expandable JSON details.
 */
import { useMemo, useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { PLATFORM_AUDIT_ACTIONS } from '../../api/platformAuditActions'
import { platformApi, type PlatformAuditEntry } from '../../api/tenantManagement'
import { platformAuditKeys } from '../../api/keys'
import { useCursorPagination } from '../../hooks/useCursorPagination'
import { usePlatformTenantList } from '../../hooks/usePlatformTenants'
import { STALE_30S } from '../../lib/queryClient'
import { Badge, Banner, Button, ListFooter, Modal, Mono, Table, type BadgeVariant, Select, EmptyState, LinesSkeleton } from '../../design/components'
import { formatDateTime } from '../../lib/format'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

function actionVariant(action: string): BadgeVariant {
  if (action.includes('SUSPEND') || action.includes('OFFBOARD')) return 'error'
  if (action.includes('CREATE') || action.includes('ACTIVATE')) return 'success'
  if (action.includes('IMPERSONAT')) return 'purple'
  return 'info'
}

/** Who acted: the admin's directory name (Phase 1), else their identity subject shortened, or a platform job. */
function actorLabel(entry: Pick<PlatformAuditEntry, 'actor_id' | 'actor_name'>): string {
  if (entry.actor_name) return entry.actor_name
  return entry.actor_id ? `${entry.actor_id.slice(0, 8)}…` : 'Platform job'
}

export function PlatformAuditLog(): JSX.Element {
  const [tenantFilter, setTenantFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const listParams = {
    ...(tenantFilter ? { tenant_id: tenantFilter } : {}),
    ...(actionFilter ? { action: actionFilter } : {}),
  }
  const {
    items: entries,
    hasMore,
    totalCount,
    loadMore,
    isLoading: loading,
    isFetchingMore,
    error: loadError,
  } = useCursorPagination(
    platformAuditKeys.list(listParams),
    (cursor) => platformApi.auditLog({ ...listParams, ...(cursor ? { cursor } : {}), limit: 50 }),
    { staleTime: STALE_30S },
  )

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load the audit log.'
    : null

  // Only the tenant filter needs the whole list; a row is labelled by the name the server joins onto it (PA-02).
  // Non-fatal: without the list the filter offers "All tenants" only.
  const { data: tenantList } = usePlatformTenantList()
  const tenants = useMemo(() => tenantList ?? [], [tenantList])

  const tenantName = (entry: PlatformAuditEntry): string => {
    if (!entry.target_tenant_id) return 'Platform'
    return entry.target_tenant_name ?? `${entry.target_tenant_id.slice(0, 8)}…`
  }

  const activeEntry = useMemo(
    () => (expandedId ? entries.find((e) => e.id === expandedId) ?? null : null),
    [entries, expandedId],
  )


  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Audit log"
            meta={
              'Every platform-level action — tenant lifecycle, impersonation sessions, settings changes.'
            }
          />
        }
        notices={
          <>
            {error && (
              <Banner variant="error" title="Couldn't load">
                {error}
              </Banner>
            )}
          </>
        }
        filters={
          <FilterBar
            label="Filter the audit log"
            activeCount={(tenantFilter ? 1 : 0) + (actionFilter ? 1 : 0)}
            onClear={() => {
              setTenantFilter('')
              setActionFilter('')
            }}
            status={
              <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', alignItems: 'center' }}>
                <Select
                  label="Tenant"
                  hideLabel
                  value={tenantFilter}
                  onChange={(e) => setTenantFilter(e.target.value)}
                >
                  <option value="">All tenants</option>
                  {tenants.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.company_name}
                    </option>
                  ))}
                </Select>
                <Select
                  label="Action"
                  hideLabel
                  value={actionFilter}
                  onChange={(e) => setActionFilter(e.target.value)}
                >
                  <option value="">All actions</option>
                  {PLATFORM_AUDIT_ACTIONS.map((a) => (
                    <option key={a} value={a}>
                      {a.replace(/_/g, ' ')}
                    </option>
                  ))}
                </Select>
              </div>
            }
          />
        }
        footer={
          <ListFooter
            shown={entries.length}
            total={totalCount}
            hasMore={hasMore}
            loading={isFetchingMore}
            onLoadMore={loadMore}
            noun="audit entries"
            nounOne="audit entry"
          />
        }
      >
        <Table
          columns={[
            { title: 'Timestamp', type: 'date' },
            { title: 'Action' },
            { title: 'Tenant' },
            { title: 'Actor', type: 'reference' },
            { title: 'IP', type: 'reference' },
            { title: '', type: 'action', width: '90px' },
          ]}
          rows={entries.map((e) => ({
            cells: [
              <Mono key="ts">{formatDateTime(e.created_at, { year: false })}</Mono>,
              <Badge key="action" variant={actionVariant(e.action)}>
                {e.action.replace(/_/g, ' ')}
              </Badge>,
              <span key="tenant" style={{ fontSize: 'var(--text-sm)' }}>
                {tenantName(e)}
              </span>,
              e.actor_name ? (
                <span key="actor" style={{ fontSize: 'var(--text-sm)' }} title={e.actor_role ?? undefined}>
                  {e.actor_name}
                </span>
              ) : (
                <Mono key="actor" color="var(--color-ink-3)">
                  <span title={e.actor_id ?? undefined}>{actorLabel(e)}</span>
                </Mono>
              ),
              <Mono key="ip" color="var(--color-ink-4)">
                {e.ip_address ?? '—'}
              </Mono>,
              e.details || e.before_state || e.after_state ? (
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
            loading ? (
              <LinesSkeleton label="Loading audit entries" />
            ) : (
              <EmptyState compact title="No audit entries match this filter" />
            )
          }
        />
      </ListPage>
      <Modal
        open={Boolean(activeEntry)}
        onClose={() => setExpandedId(null)}
        title={activeEntry ? activeEntry.action.replace(/_/g, ' ') : 'Audit details'}
        size="md"
        footer={
          <Button variant="secondary" onClick={() => setExpandedId(null)}>
            Close
          </Button>
        }
      >
        {activeEntry && (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2) var(--space-4)', marginBottom: 'var(--space-4)', fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
              <span>Tenant: <strong style={{ color: 'var(--color-ink)' }}>{tenantName(activeEntry)}</strong></span>
              <span>Actor: <strong style={{ color: 'var(--color-ink)' }}>{actorLabel(activeEntry)}</strong>{activeEntry.actor_role ? ` (${activeEntry.actor_role})` : ''}</span>
              <span>When: <Mono>{formatDateTime(activeEntry.created_at)}</Mono></span>
              {activeEntry.ip_address && <span>IP: <Mono>{activeEntry.ip_address}</Mono></span>}
            </div>
            <pre
              style={{
                margin: 0,
                padding: 'var(--space-4)',
                borderRadius: 'var(--radius-md)',
                background: 'var(--color-surface-muted)',
                border: '1px solid var(--color-line-soft)',
                fontSize: 'var(--text-xs)',
                fontFamily: 'var(--font-mono)',
                whiteSpace: 'pre-wrap',
                overflowX: 'auto',
              }}
            >
              {JSON.stringify(activeEntry.details ?? {}, null, 2)}
            </pre>
            {(activeEntry.before_state || activeEntry.after_state) && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
                {(['before_state', 'after_state'] as const).map((key) => (
                  <div key={key}>
                    <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, marginBottom: 'var(--space-1)' }}>
                      {key === 'before_state' ? 'Before' : 'After'}
                    </div>
                    <pre style={{ margin: 0, padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'var(--color-surface-muted)', fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap' }}>
                      {JSON.stringify(activeEntry[key] ?? {}, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Modal>
    </>
  )
}
