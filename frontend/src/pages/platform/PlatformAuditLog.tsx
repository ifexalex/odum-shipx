/**
 * 14.7 — Platform Audit Log (Section 14 of the prototype, reports-screens.jsx).
 *
 * Cross-tenant audit trail: tenant lifecycle events, impersonation sessions,
 * settings changes. Filters by tenant and action; expandable JSON details.
 */
import { useCallback, useMemo, useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { platformApi } from '../../api/tenantManagement'
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

const COMMON_ACTIONS = [
  'TENANT_CREATED',
  'TENANT_SUSPENDED',
  'TENANT_ACTIVATED',
  'TENANT_OFFBOARDED',
  'IMPERSONATION_STARTED',
  'IMPERSONATION_ENDED',
  'QUOTA_OVERRIDE_SET',
  'PLAN_UPDATED',
  'SETTINGS_UPDATED',
]

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

  // The filter dropdown degrades to truncated raw IDs if this fails — non-fatal,
  // so the query's error is deliberately not surfaced.
  const { data: tenantList } = usePlatformTenantList()
  // Memoised because `?? []` would be a fresh array every render, which would
  // re-create the `tenantName` callback below on every render.
  const tenants = useMemo(() => tenantList?.data ?? [], [tenantList])

  const tenantName = useCallback(
    (id: string | null): string => {
      if (!id) return 'Platform'
      return tenants.find((t) => t.id === id)?.company_name ?? id.slice(0, 8)
    },
    [tenants],
  )

  const activeEntry = useMemo(
    () => (expandedId ? entries.find((e) => e.id === expandedId) ?? null : null),
    [entries, expandedId],
  )

  const actionOptions = useMemo(() => {
    const set = new Set<string>(COMMON_ACTIONS)
    for (const e of entries) set.add(e.action)
    if (actionFilter) set.add(actionFilter)
    return Array.from(set)
  }, [entries, actionFilter])

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
                  {actionOptions.map((a) => (
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
                {tenantName(e.target_tenant_id)}
              </span>,
              <Mono key="ip" color="var(--color-ink-4)">
                {e.ip_address ?? '—'}
              </Mono>,
              e.details ? (
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
              <span>Tenant: <strong style={{ color: 'var(--color-ink)' }}>{tenantName(activeEntry.target_tenant_id)}</strong></span>
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
          </>
        )}
      </Modal>
    </>
  )
}
