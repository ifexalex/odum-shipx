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
import { Badge, Banner, Button, Card, ListFooter, Mono, Table, type BadgeVariant, Select, EmptyState, LinesSkeleton } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import { formatDateTime } from '../../lib/format'

function actionVariant(action: string): BadgeVariant {
  if (action.includes('SUSPEND') || action.includes('OFFBOARD')) return 'error'
  if (action.includes('CREATE') || action.includes('ACTIVATE')) return 'success'
  if (action.includes('IMPERSONAT')) return 'purple'
  return 'info'
}

export function PlatformAuditLog(): JSX.Element {
  const [tenantFilter, setTenantFilter] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // The hand-rolled version kept its own cursor/hasMore/totalCount state and
  // appended pages by hand; `useCursorPagination` is that exact pattern, and
  // the tenant filter is part of the key so switching it starts a fresh page 1
  // instead of appending onto the previous tenant's rows.
  const listParams = tenantFilter ? { tenant_id: tenantFilter } : {}
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

  useTopBarSlot({ subtitle: 'Every platform-level action — tenant lifecycle, impersonation sessions, settings changes.' })

  return (
    <div>

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Couldn't load">{error}</Banner></div>}

      <div style={{ display: 'flex', gap: 'var(--space-3)', marginBottom: 'var(--space-4)', alignItems: 'center' }}>
        <Select label="Tenant"
          value={tenantFilter}
          onChange={(e) => setTenantFilter(e.target.value)}
        >
          <option value="">All tenants</option>
          {tenants.map((t) => (
            <option key={t.id} value={t.id}>{t.company_name}</option>
          ))}
        </Select>
      </div>

      <Card padding="none">
        <Table
          columns={[
            { title: 'Timestamp' },
            { title: 'Action' },
            { title: 'Tenant' },
            { title: 'IP' },
            { title: '', width: '90px' },
          ]}
          rows={entries.map((e) => ({
            cells: [
              <Mono key="ts">{formatDateTime(e.created_at, { year: false })}</Mono>,
              <Badge key="action" variant={actionVariant(e.action)}>{e.action.replace(/_/g, ' ')}</Badge>,
              <span key="tenant" style={{ fontSize: 'var(--text-sm)' }}>{tenantName(e.target_tenant_id)}</span>,
              <Mono key="ip" color="var(--color-ink-4)">{e.ip_address ?? '—'}</Mono>,
              e.details ? (
                <Button
                  key="details"
                  variant="ghost"
                  size="sm"
                  onClick={() => setExpandedId(expandedId === e.id ? null : e.id)}
                >
                  {expandedId === e.id ? 'Hide' : 'Details'}
                </Button>
              ) : (
                <span key="details" />
              ),
            ],
          }))}
          emptyState={loading ? <LinesSkeleton label="Loading audit entries" /> : <EmptyState compact title="No audit entries match this filter" />}
        />
      </Card>

      {expandedId && (
        <div style={{ marginTop: 'var(--space-3)' }}>
          <Card padding="default">
            <pre style={{ margin: 0, fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', overflowX: 'auto' }}>
              {JSON.stringify(entries.find((e) => e.id === expandedId)?.details ?? {}, null, 2)}
            </pre>
          </Card>
        </div>
      )}

      <ListFooter
        shown={entries.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="audit entries"
      />
    </div>
  )
}
