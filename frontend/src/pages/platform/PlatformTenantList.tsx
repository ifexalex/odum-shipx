/**
 * 2.2 — Tenant List (audit gap B2, prototype platform-screens.jsx TenantList).
 *
 * Status filter chips with counts, search, and the prototype's richer columns:
 * tenant cell (initials avatar + slug), mono ID, contact name+email cell,
 * users x/limit. Filtering/search run client-side over the fetched list — the
 * platform has tens of tenants, one page. Deliberately absent (AUDIT_GAPS):
 * "Onboarding" status (not a backend status) and bulk actions (no bulk
 * endpoints).
 */
import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { type Tenant, type TenantStatus } from '../../api/tenantManagement'
import { usePlatformTenantList } from '../../hooks/usePlatformTenants'
import { Banner, Button, Card, Chip, Field, Mono, StatusBadge, Table, ViewLink } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './admin.module.css'
import { formatDate } from '../../lib/format'
import { statusLabel, statusesOf } from '../../design/status'

const TIER_COLOR: Record<string, string> = {
  starter: 'var(--color-ink-3)',
  business: 'var(--color-primary)',
  enterprise: 'var(--color-accent)',
}

function initialsFor(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  return (
    words
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join('') || '?'
  )
}

// Stable per-tenant avatar hue from the id, prototype-style variety.
const AVATAR_COLORS = [
  'var(--color-accent)',
  'var(--color-primary-text)',
  'var(--color-info)',
  'var(--color-warning)',
  'var(--color-role-platform)',
  'var(--color-role-china)',
]

function avatarColor(id: string): string {
  let hash = 0
  for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) % 997
  return AVATAR_COLORS[hash % AVATAR_COLORS.length]!
}

function TenantCell({ tenant }: { tenant: Tenant }): JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', minWidth: 0 }}>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 'var(--radius-md)',
          flexShrink: 0,
          background: `color-mix(in srgb, ${avatarColor(tenant.id)} 15%, transparent)`,
          color: avatarColor(tenant.id),
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 700,
          fontSize: 'var(--text-xs)',
          fontFamily: 'var(--font-display)',
        }}
      >
        {initialsFor(tenant.company_name)}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)', lineHeight: 'var(--leading-tight)' }}>{tenant.company_name}</div>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', lineHeight: 'var(--leading-tight)' }}>
          {tenant.slug}
        </div>
      </div>
    </div>
  )
}

export function PlatformTenantList(): JSX.Element {
  const navigate = useNavigate()
  const { data: tenantsResult, isLoading: loading, error } = usePlatformTenantList()
  const tenants = useMemo(() => tenantsResult?.data ?? [], [tenantsResult])

  const [statusFilter, setStatusFilter] = useState<TenantStatus | null>(null)
  const [query, setQuery] = useState('')

  const counts = useMemo(() => {
    const map: Record<TenantStatus, number> = { active: 0, suspended: 0, offboarded: 0 }
    for (const t of tenants) map[t.status] += 1
    return map
  }, [tenants])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return tenants.filter((t) => {
      if (statusFilter && t.status !== statusFilter) return false
      if (!q) return true
      return (
        t.company_name.toLowerCase().includes(q) ||
        (t.primary_contact_email ?? '').toLowerCase().includes(q) ||
        (t.slug ?? '').toLowerCase().includes(q) ||
        t.id.toLowerCase().includes(q)
      )
    })
  }, [tenants, statusFilter, query])

  useTopBarSlot({
    subtitle: 'All onboarded tenants and their subscription status.',
    actions: (
      <Button variant="primary" icon="plus" onClick={() => navigate('/platform/tenants/new')}>
        Onboard tenant
      </Button>
    ),
  })

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error.message}</Banner>
        </div>
      )}

      <Card padding="default">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
              All {tenants.length > 0 && <span style={{ opacity: 0.6 }}>{tenants.length}</span>}
            </Chip>
            {statusesOf('tenant').map((status) => (
              <Chip
                key={status}
                active={statusFilter === status}
                onClick={() => setStatusFilter(statusFilter === status ? null : status)}
              >
                {statusLabel('tenant', status)} <span style={{ opacity: 0.6 }}>{counts[status]}</span>
              </Chip>
            ))}
          </div>
          <div style={{ flex: 1, minWidth: 220 }}>
            <Field
              label=""
              name="tenantSearch"
              icon="search"
              placeholder="Search by name, email, slug, or ID…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding="none">
          <Table
            columns={[
              { title: 'Tenant' },
              { title: 'ID' },
              { title: 'Status' },
              { title: 'Plan' },
              { title: 'Primary contact' },
              { title: 'Users', align: 'right' },
              { title: 'Created' },
              { title: '', width: '60px' },
            ]}
            rows={visible.map((t) => ({
              cells: [
                <TenantCell key="tenant" tenant={t} />,
                <Mono key="id" color="var(--color-ink-4)">
                  <span title={t.id}>{t.id.slice(0, 8)}…</span>
                </Mono>,
                <StatusBadge key="status" kind="tenant" status={t.status} />,
                <span
                  key="tier"
                  style={{
                    fontSize: 'var(--text-xs)',
                    fontWeight: 700,
                    color: TIER_COLOR[t.subscription_tier] ?? 'var(--color-ink-2)',
                    textTransform: 'capitalize',
                  }}
                >
                  {t.subscription_tier}
                </span>,
                <span key="contact" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {t.primary_contact_email}
                </span>,
                <Mono key="users">
                  {t.user_count != null
                    ? `${t.user_count}${t.users_limit != null ? ` / ${t.users_limit}` : ''}`
                    : '—'}
                </Mono>,
                <span key="date" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {formatDate(t.created_at)}
                </span>,
                <ViewLink
                  key="view"
                  onClick={() =>
                    navigate(`/platform/tenants/${t.id}`, {
                      state: { tenant: t },
                    })
                  }
                />,
              ],
            }))}
            loading={loading}
            emptyState={
              !loading && visible.length === 0 ? (
                <span>
                  {tenants.length === 0
                    ? 'No tenants onboarded yet.'
                    : 'No tenants match the current filter.'}
                </span>
              ) : undefined
            }
          />
        </Card>
        {!loading && tenants.length > 0 && (
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginTop: 'var(--space-3)' }}>
            Showing {visible.length} of {tenants.length} tenant(s)
          </p>
        )}
      </div>
    </div>
  )
}
