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
import {
  Badge,
  Banner,
  Button,
  Card,
  Chip,
  Field,
  Mono,
  Table,
  ViewLink,
  type BadgeVariant,
} from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './admin.module.css'
import { formatDate } from '../../lib/format'

const STATUS_VARIANT: Record<TenantStatus, BadgeVariant> = {
  active: 'success',
  suspended: 'error',
  offboarded: 'neutral',
}

const STATUS_LABELS: Record<TenantStatus, string> = {
  active: 'Active',
  suspended: 'Suspended',
  offboarded: 'Offboarded',
}

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
  'var(--color-primary)',
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
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 6,
          flexShrink: 0,
          background: `color-mix(in srgb, ${avatarColor(tenant.id)} 15%, transparent)`,
          color: avatarColor(tenant.id),
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 800,
          fontSize: 12,
          fontFamily: 'var(--font-display)',
        }}
      >
        {initialsFor(tenant.company_name)}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.2 }}>{tenant.company_name}</div>
        <div style={{ fontSize: 11, color: 'var(--color-ink-4)', lineHeight: 1.3 }}>
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

      <Card padding={16}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
              All {tenants.length > 0 && <span style={{ opacity: 0.6 }}>{tenants.length}</span>}
            </Chip>
            {(Object.keys(STATUS_LABELS) as TenantStatus[]).map((status) => (
              <Chip
                key={status}
                active={statusFilter === status}
                onClick={() => setStatusFilter(statusFilter === status ? null : status)}
              >
                {STATUS_LABELS[status]} <span style={{ opacity: 0.6 }}>{counts[status]}</span>
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
        <Card padding={0}>
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
                <Badge key="status" variant={STATUS_VARIANT[t.status]}>
                  {STATUS_LABELS[t.status]}
                </Badge>,
                <span
                  key="tier"
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    color: TIER_COLOR[t.subscription_tier] ?? 'var(--color-ink-2)',
                    textTransform: 'capitalize',
                  }}
                >
                  {t.subscription_tier}
                </span>,
                <span key="contact" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
                  {t.primary_contact_email}
                </span>,
                <Mono key="users">
                  {t.user_count != null
                    ? `${t.user_count}${t.users_limit != null ? ` / ${t.users_limit}` : ''}`
                    : '—'}
                </Mono>,
                <span key="date" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
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
          <p style={{ fontSize: 12, color: 'var(--color-ink-4)', marginTop: 10 }}>
            Showing {visible.length} of {tenants.length} tenant(s)
          </p>
        )}
      </div>
    </div>
  )
}
