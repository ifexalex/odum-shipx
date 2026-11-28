/**
 * 2.1 — Platform Dashboard (Section 2 of the prototype, platform-screens.jsx).
 *
 * Platform admin's landing page: cross-tenant aggregates, tier mix, a
 * tenant-health table (staff seats x/limit, every tenant: the list is followed page by page), a recent
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
import { useOnboardingRequests } from '../../hooks/useOnboardingRequests'
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
  // Activity feed & onboarding leads are non-fatal — the dashboard renders without them.
  const recent = useRecentPlatformActivity(8)
  const onboarding = useOnboardingRequests()

  const stats = dashboard.data ?? null
  const tenants = useMemo(() => tenantList.data ?? [], [tenantList.data])
  const pendingLeads = useMemo(
    () => (onboarding.data ?? []).filter((r) => r.status === 'new' || r.status === 'contacted' || r.status === 'approved').length,
    [onboarding.data],
  )
  // Sort tenant health so tenants needing attention (suspended, then over-quota) surface at the top.
  const prioritizedTenants = useMemo(() => {
    const score = (t: (typeof tenants)[number]): number => {
      if (t.status === 'suspended') return 0
      if (t.user_count != null && t.users_limit != null && t.user_count >= t.users_limit) return 1
      if (t.status === 'active') return 2
      return 3
    }
    return [...tenants].sort((a, b) => score(a) - score(b))
  }, [tenants])
  const activity = recent.data?.data ?? []
  const loading = dashboard.isLoading || tenantList.isLoading
  const failure = dashboard.error ?? tenantList.error
  const error = failure
    ? failure instanceof ApiError
      ? failure.message
      : 'Could not load the platform dashboard.'
    : null


  if (loading) return <PageSkeleton kind="list" label="Loading platform dashboard" />

  return (
    <div>
      <PageHeader
        title="Platform dashboard"
        meta="Health and growth across every tenant on ShipX."
        actions={
          <Button variant="primary" icon="plus" onClick={() => navigate('/platform/tenants/new')}>
            Onboard tenant
          </Button>
        }
      />

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Couldn't load">{error}</Banner></div>}

      {stats && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
            <StatCard
              label="Active tenants"
              value={stats.tenants.active_tenants}
              sublabel={`${stats.tenants.starter_tenants} Starter · ${stats.tenants.business_tenants} Business · ${stats.tenants.enterprise_tenants} Ent.`}
              onSelect={() => navigate('/platform/tenants')}
            />
            <StatCard
              label="Suspended"
              value={stats.tenants.suspended_tenants}
              sublabel={stats.tenants.suspended_tenants > 0 ? 'review status' : 'none suspended'}
              onSelect={() => navigate('/platform/tenants')}
            />
            <StatCard
              label="Pending onboarding"
              value={onboarding.data ? pendingLeads : '—'}
              sublabel={pendingLeads > 0 ? 'leads awaiting action' : 'queue clear'}
              onSelect={() => navigate('/platform/onboarding-requests')}
            />
            <StatCard label="Total staff users" value={stats.total_users} sublabel={`${stats.total_containers} containers`} />
          </div>
        </>
      )}

      <div className={styles.dashCols}>
        <Card padding="none">
          <div className={styles.cardHeader}>
            <SectionHead
              title="Tenant health"
              sub={`${plural(tenants.length, 'tenant')} · suspended and over-quota listed first`}
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
            rows={prioritizedTenants.slice(0, 8).map((t) => {
              const overQuota = t.user_count != null && t.users_limit != null && t.user_count > t.users_limit
              return {
                suspended: t.status === 'suspended',
                onOpen: () => navigate(`/platform/tenants/${t.id}`),
                cells: [
                  <UserCell key="name" name={t.company_name} email={t.primary_contact_email ?? ''} />,
                  <Badge key="tier" variant="info">{t.subscription_tier}</Badge>,
                  <StatusBadge key="status" kind="tenant" status={t.status} />,
                  <span key="users" style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                    <Mono color={overQuota ? 'var(--color-warning)' : undefined}>
                      {t.user_count != null ? `${t.user_count}${t.users_limit != null ? ` / ${t.users_limit}` : ''}` : '—'}
                    </Mono>
                    {overQuota && <Badge variant="warning" size="sm" dot={false}>Over quota</Badge>}
                  </span>,
                ],
              }
            })}
            emptyState={<EmptyState compact title="No tenants yet" />}
          />
        </Card>

        <Card padding="none">
          <div className={styles.cardHeader}>
            <SectionHead title="Recent activity" sub="Platform-level events" />
          </div>
          <div>
            {activity.length === 0 && (
              <div style={{ padding: 'var(--space-5)', fontSize: 'var(--text-sm)', color: 'var(--color-ink-4)' }}>No recent activity.</div>
            )}
            {activity.map((e, i) => (
              <div
                key={e.id}
                style={{ display: 'flex', gap: 'var(--space-3)', padding: 'var(--space-3) var(--space-5)', borderTop: i > 0 ? '1px solid var(--color-line-soft)' : 'none' }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--space-1) var(--space-2)' }}>
                    <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink)', fontWeight: 600 }}>{e.target_tenant_name ?? (e.target_tenant_id ? `${e.target_tenant_id.slice(0, 8)}…` : 'Platform')}</div>
                    <Badge variant={actionVariant(e.action)} size="sm" dot={false}>{e.action.replace(/_/g, ' ')}</Badge>
                  </div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginTop: 'var(--space-0-5)' }}>{relativeTime(e.created_at)}</div>
                </div>
              </div>
            ))}
            <div className={styles.cardFooter}>
              <Link to="/platform/audit-log" style={{ color: 'var(--color-primary-text)', fontWeight: 600, fontSize: 'var(--text-xs)', textDecoration: 'none' }}>
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
