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
import { Badge, Banner, Button, Chip, Mono, StatusBadge, Table, SearchField, EmptyState } from '../../design/components'
import { formatDate, plural } from '../../lib/format'
import { statusLabel, statusesOf } from '../../design/status'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'
import { initialsFor } from '../../lib/initials'
import styles from './admin.module.css'
import { formatDate } from '../../lib/format'

const TIER_COLOR: Record<string, string> = {
  starter: 'var(--color-ink-3)',
  business: 'var(--color-primary)',
  enterprise: 'var(--color-accent)',
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
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', lineHeight: 'var(--leading-tight)', display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
          <span>{tenant.slug}</span>
          <span>·</span>
          <Mono color="var(--color-ink-4)">
            <span title={tenant.id}>{tenant.id.slice(0, 8)}…</span>
          </Mono>
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

  return (
    <ListPage
      header={
        <PageHeader
          title="Tenants"
          meta={'All onboarded tenants and their subscription status.'}
          primary={
            <Button variant="primary" icon="plus" onClick={() => navigate('/platform/tenants/new')}>
              Onboard tenant
            </Button>
          }
        />
      }
      notices={<>{error && <Banner variant="error">{error.message}</Banner>}</>}
      filters={
        <FilterBar
          label="Filter tenants"
          status={
            <>
              <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
                All {tenants.length > 0 && <span style={{ opacity: 0.6 }}>{tenants.length}</span>}
              </Chip>
              {statusesOf('tenant').map((status) => (
                <Chip
                  key={status}
                  active={statusFilter === status}
                  onClick={() => setStatusFilter(statusFilter === status ? null : status)}
                >
                  {statusLabel('tenant', status)}{' '}
                  <span style={{ opacity: 0.6 }}>{counts[status]}</span>
                </Chip>
              ))}
            </>
          }
          search={
            <>
              <SearchField
                label="Search tenants"
                placeholder="Search by name, email, slug, or ID…"
                value={query}
                onChange={setQuery}
              />
            </>
          }
        />
      }
      footer={
        !loading &&
        tenants.length > 0 && (
          <p className={styles.showing}>
            Showing {visible.length} of {plural(tenants.length, 'tenant')}
          </p>
        )
      }
    >
      <Table
        columns={[
          { title: 'Tenant' },
          { title: 'Status', type: 'status' },
          { title: 'Plan' },
          { title: 'Primary contact' },
          { title: 'Users', type: 'number' },
          { title: 'Created', type: 'date' },
        ]}
        rows={visible.map((t) => {
          const overQuota = t.user_count != null && t.users_limit != null && t.user_count > t.users_limit
          return {
            onOpen: () => navigate(`/platform/tenants/${t.id}`, { state: { tenant: t } }),
            cells: [
              <TenantCell key="tenant" tenant={t} />,
              <StatusBadge key="status" kind="tenant" status={t.status} />,
              <span
                key="tier"
                style={{
                  fontSize: 'var(--text-xs)',
                  fontWeight: 700,
                  color: TIER_COLOR[t.subscription_tier] ?? 'var(--color-ink-2)',
                  textTransform: 'capitalize',
                  whiteSpace: 'nowrap',
                }}
              >
                {t.subscription_tier}
              </span>,
              <span key="contact" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                {t.primary_contact_email}
              </span>,
              <span
                key="users"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', whiteSpace: 'nowrap' }}
              >
                <Mono color={overQuota ? 'var(--color-warning)' : undefined}>
                  {t.user_count != null
                    ? `${t.user_count}${t.users_limit != null ? ` / ${t.users_limit >= 999999 ? '∞' : t.users_limit}` : ''}`
                    : '—'}
                </Mono>
                {overQuota && <Badge variant="warning" size="sm" dot={false}>Over quota</Badge>}
              </span>,
              <span
                key="date"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', whiteSpace: 'nowrap' }}
              >
                {formatDate(t.created_at)}
              </span>,
            ],
          }
        })}
        loading={loading}
        emptyState={
          !loading && visible.length === 0 ? (
            <EmptyState
              compact
              title={
                tenants.length === 0
                  ? 'No tenants onboarded yet'
                  : 'No tenants match the current filter'
              }
            />
          ) : undefined
        }
      />
    </ListPage>
  )
}
