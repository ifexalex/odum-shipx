/**
 * 14.7 — Platform Audit Log (Section 14 of the prototype, reports-screens.jsx).
 *
 * Cross-tenant audit trail: tenant lifecycle events, impersonation sessions,
 * settings changes. Filters by tenant and action; expandable JSON details.
 */
import { useCallback, useEffect, useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { platformApi, type PlatformAuditEntry, type Tenant } from '../../api/tenantManagement'
import { Badge, Banner, Button, Card, ListFooter, Mono, Table, type BadgeVariant } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'

function actionVariant(action: string): BadgeVariant {
  if (action.includes('SUSPEND') || action.includes('OFFBOARD')) return 'error'
  if (action.includes('CREATE') || action.includes('ACTIVATE')) return 'success'
  if (action.includes('IMPERSONAT')) return 'purple'
  return 'info'
}

export function PlatformAuditLog(): JSX.Element {
  const [entries, setEntries] = useState<PlatformAuditEntry[]>([])
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [tenantFilter, setTenantFilter] = useState('')
  const [cursor, setCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const tenantName = useCallback(
    (id: string | null): string => {
      if (!id) return 'Platform'
      return tenants.find((t) => t.id === id)?.company_name ?? id.slice(0, 8)
    },
    [tenants],
  )

  const load = useCallback(
    async (nextCursor?: string) => {
      setLoading(true)
      setError(null)
      try {
        const result = await platformApi.auditLog({
          ...(tenantFilter ? { tenant_id: tenantFilter } : {}),
          ...(nextCursor ? { cursor: nextCursor } : {}),
          limit: 50,
        })
        setEntries((prev) => (nextCursor ? [...prev, ...result.data] : result.data))
        setCursor(result.meta.pagination.next_cursor)
        setHasMore(result.meta.pagination.has_more)
        setTotalCount(result.meta.pagination.total_count)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load the audit log.')
      } finally {
        setLoading(false)
      }
    },
    [tenantFilter],
  )

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void (async () => {
      try {
        setTenants((await platformApi.listTenants()).data)
      } catch {
        // filter dropdown degrades to raw IDs — non-fatal
      }
    })()
  }, [])

  useTopBarSlot({ subtitle: 'Every platform-level action — tenant lifecycle, impersonation sessions, settings changes.' })

  return (
    <div>

      {error && <div style={{ marginBottom: 16 }}><Banner variant="error" title="Couldn't load">{error}</Banner></div>}

      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-2)' }}>Tenant</label>
        <select
          style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid var(--color-line)', background: 'var(--color-surface)', fontSize: '0.875rem', minWidth: 220 }}
          value={tenantFilter}
          onChange={(e) => setTenantFilter(e.target.value)}
        >
          <option value="">All tenants</option>
          {tenants.map((t) => (
            <option key={t.id} value={t.id}>{t.company_name}</option>
          ))}
        </select>
      </div>

      <Card padding={0}>
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
              <Mono key="ts">{new Date(e.created_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</Mono>,
              <Badge key="action" variant={actionVariant(e.action)}>{e.action.replace(/_/g, ' ')}</Badge>,
              <span key="tenant" style={{ fontSize: 13 }}>{tenantName(e.target_tenant_id)}</span>,
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
          emptyState={
            <span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>
              {loading ? 'Loading audit entries…' : 'No audit entries match this filter.'}
            </span>
          }
        />
      </Card>

      {expandedId && (
        <div style={{ marginTop: 12 }}>
          <Card padding={16}>
            <pre style={{ margin: 0, fontSize: 12, fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', overflowX: 'auto' }}>
              {JSON.stringify(entries.find((e) => e.id === expandedId)?.details ?? {}, null, 2)}
            </pre>
          </Card>
        </div>
      )}

      <ListFooter
        shown={entries.length}
        total={totalCount}
        hasMore={hasMore}
        loading={loading}
        onLoadMore={() => void load(cursor ?? undefined)}
        noun="audit entries"
      />
    </div>
  )
}
