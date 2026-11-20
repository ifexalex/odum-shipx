/**
 * 2.1 — Platform Dashboard (Section 2 of the prototype, platform-screens.jsx).
 *
 * Platform admin's landing page: cross-tenant aggregates, tier mix, a
 * tenant-health table (with users x/limit from the list endpoint), a recent
 * activity feed (from the platform audit log), and quick-action tiles.
 *
 * Deliberately absent (AUDIT_GAPS): per-tenant "containers x/limit" column
 * (no batch usage endpoint — would be N calls); MRR / API-call stats / trend
 * chips (no historical-aggregates source — fictional in the prototype).
 */
import { useMemo, type JSX } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { usePlatformDashboardStats, usePlatformTenantList, useRecentPlatformActivity } from '../../hooks/usePlatformTenants'
import { Badge, Banner, Button, Card, Mono, QuickActionCard, StatCard, StatusBadge, Table, type BadgeVariant, type IconName, UserCell, Icon, PageSkeleton, EmptyState } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './admin.module.css'
import { plural } from '../../lib/format'

function actionVariant(action: string): BadgeVariant {
  if (action.includes('SUSPEND') || action.includes('OFFBOARD') || action.includes('DELETE')) return 'error'
  if (action.includes('CREATE') || action.includes('ACTIVATE')) return 'success'
  if (action.includes('IMPERSONAT')) return 'purple'
  return 'info'
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  const mins = Math.round((Date.now() - then) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

interface QuickAction {
  icon: IconName
  title: string
  sub: string
  cta: string
  to: string
  accent?: boolean
}

const QUICK_ACTIONS: QuickAction[] = [
  { icon: 'plus', title: 'Onboard new tenant', sub: 'Create a tenant account and provision an admin user', cta: 'Start onboarding', to: '/platform/tenants/new', accent: true },
  { icon: 'log', title: 'View full audit log', sub: 'Cross-tenant audit events with filters and JSON diffs', cta: 'Open audit log', to: '/platform/audit-log' },
  { icon: 'settings', title: 'Platform settings', sub: 'Notification gateways, plans, maintenance windows', cta: 'Open settings', to: '/platform/settings' },
]

export function PlatformDashboard(): JSX.Element {
  const navigate = useNavigate()
  const dashboard = usePlatformDashboardStats()
  const tenantList = usePlatformTenantList()
  // Activity feed is non-fatal — the dashboard renders without it.
  const recent = useRecentPlatformActivity(8)

  const stats = dashboard.data ?? null
  const tenants = useMemo(() => tenantList.data?.data ?? [], [tenantList.data])
  const activity = recent.data?.data ?? []
  const loading = dashboard.isLoading || tenantList.isLoading
  const failure = dashboard.error ?? tenantList.error
  const error = failure
    ? failure instanceof ApiError
      ? failure.message
      : 'Could not load the platform dashboard.'
    : null

  const tenantName = useMemo(() => {
    const map = new Map(tenants.map((t) => [t.id, t.company_name]))
    return (id: string | null) => (id ? (map.get(id) ?? `${id.slice(0, 8)}…`) : 'Platform')
  }, [tenants])

  if (loading) return <PageSkeleton kind="list" label="Loading platform dashboard" />

  return (
    <div>
      <PageHeader
        title="Platform dashboard"
        meta="Health and growth across every tenant on ShipX."
        actions={
          <Button variant="primary" icon="plus" onClick={() => navigate('/platform/tenants')}>
            Onboard tenant
          </Button>
        }
      />

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Couldn't load">{error}</Banner></div>}

      {stats && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 'var(--space-3)', marginBottom: 'var(--space-5)' }}>
            <StatCard label="Active tenants" value={stats.tenants.active_tenants} />
            <StatCard label="Suspended" value={stats.tenants.suspended_tenants} />
            <StatCard label="Total staff users" value={stats.total_users} />
            <StatCard label="Total containers" value={stats.total_containers} />
          </div>

          <div style={{ marginBottom: 'var(--space-5)' }}>
            <Card padding="default">
              <SectionHead title="Subscription mix" sub="Tenants by plan tier" />
              <div style={{ display: 'flex', gap: 'var(--space-6)', marginTop: 'var(--space-3)', flexWrap: 'wrap' }}>
                {(
                  [
                    ['Starter', stats.tenants.starter_tenants],
                    ['Business', stats.tenants.business_tenants],
                    ['Enterprise', stats.tenants.enterprise_tenants],
                  ] as const
                ).map(([label, count]) => (
                  <div key={label} style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-2)' }}>
                    <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-2xl)' }}>{count}</span>
                    <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>{label}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}

      <div className={styles.dashCols}>
        <Card padding="none">
          <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
            <SectionHead
              title="Tenant health"
              sub={`${plural(tenants.length, 'tenant')} on the platform`}
              action={
                <Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate('/platform/tenants')}>
                  Manage tenants
                </Button>
              }
            />
          </div>
          <Table
            columns={[
              { title: 'Tenant' },
              { title: 'Tier' },
              { title: 'Status', type: 'status' },
              { title: 'Users', type: 'number' },
            ]}
            rows={tenants.slice(0, 8).map((t) => ({
              suspended: t.status === 'suspended',
              onOpen: () => navigate(`/platform/tenants/${t.id}`),
              cells: [
                <UserCell key="name" name={t.company_name} email={t.primary_contact_email ?? ''} />,
                <Badge key="tier" variant="info">{t.subscription_tier}</Badge>,
                <StatusBadge key="status" kind="tenant" status={t.status} />,
                <Mono key="users">
                  {t.user_count != null ? `${t.user_count}${t.users_limit != null ? ` / ${t.users_limit}` : ''}` : '—'}
                </Mono>,
              ],
            }))}
            emptyState={<EmptyState compact title="No tenants yet" />}
          />
        </Card>

        <Card padding="none">
          <div style={{ padding: 'var(--space-5) var(--space-5) var(--space-3)' }}>
            <SectionHead title="Recent activity" sub="Platform-level events" />
          </div>
          <div>
            {activity.length === 0 && (
              <div style={{ padding: '0 var(--space-5) var(--space-5)', fontSize: 'var(--text-sm)', color: 'var(--color-ink-4)' }}>No recent activity.</div>
            )}
            {activity.map((e, i) => (
              <div
                key={e.id}
                style={{ display: 'flex', gap: 'var(--space-3)', padding: 'var(--space-3) var(--space-5)', borderTop: i > 0 ? '1px solid var(--color-line-soft)' : 'none' }}
              >
                <div style={{ paddingTop: 'var(--space-0-5)' }}>
                  <Badge variant={actionVariant(e.action)} size="sm">{e.action.replace(/_/g, ' ')}</Badge>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', fontWeight: 500 }}>{tenantName(e.target_tenant_id)}</div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginTop: 'var(--space-0-5)' }}>{relativeTime(e.created_at)}</div>
                </div>
              </div>
            ))}
            <div style={{ padding: 'var(--space-3) var(--space-5)', borderTop: '1px solid var(--color-line-soft)', textAlign: 'center' }}>
              <Link to="/platform/audit-log" style={{ color: 'var(--color-primary-text)', fontWeight: 600, fontSize: 'var(--text-sm)' }}>
                View full audit log <Icon name="arrowright" size={12} />
              </Link>
            </div>
          </div>
        </Card>
      </div>

      <div style={{ marginTop: 'var(--space-6)' }}>
        <SectionHead title="Quick actions" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--space-4)', marginTop: 'var(--space-3)' }}>
          {QUICK_ACTIONS.map((a) => (
            <QuickActionCard
              key={a.title}
              icon={a.icon}
              title={a.title}
              sub={a.sub}
              cta={a.cta}
              accent={a.accent}
              onAction={() => navigate(a.to)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
