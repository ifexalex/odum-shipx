/**
 * Shared dashboard for tenant_admin and nigeria_office_staff.
 * Shows summary stats from billing and containers via existing APIs.
 */

import { useMemo, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { billingApi } from '../../api/billing'
import { claimsApi } from '../../api/claims'
import { } from '../../api/containerRules'
import { billingKeys, claimKeys, containerKeys, customerKeys } from '../../api/keys'
import { formatNgnCompact, formatDate, formatNgn } from '../../lib/format'
import { ARRIVED_IN_NG } from '../../api/manifestRules'
import { customersApi } from '../../api/tenantManagement'
import { containersApi } from '../../api/tracking'
import { useSession } from '../../auth/useSession'
import {
  useActiveReleaseNotes,
  useOpenDisputes,
  useOutstandingBilling,
  usePendingManifests,
  usePendingPackingLists,
  useRecentContainers,
} from '../../hooks/useDashboard'
import { Badge, Button, Card, Mono, QuickActionCard, StatCard, StatusBadge, Table, UserCell, EmptyState } from '../../design/components'
import { ContainerPipeline } from './DashboardPipeline'
import { ActivityFeed } from '../../shell/ActivityFeed'
import { PlanUsagePanel } from '../../shell/PlanUsagePanel'
import { SectionHead } from '../../shell/SectionHead'
import { UnbilledQueue } from '../../shell/UnbilledQueue'
import styles from './admin.module.css'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

export function Dashboard(): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()

  const isAdmin = session?.role === 'tenant_admin'
  const isNigeria = session?.role === 'nigeria_office_staff'

  // Tenant-wide aggregates — computed server-side so every figure stays
  // correct no matter how many rows a list endpoint would return.
  const { data: containerStats } = useQuery({
    queryKey: containerKeys.stats(),
    queryFn: containersApi.stats,
  })
  const { data: billingStats } = useQuery({
    queryKey: billingKeys.stats(),
    queryFn: billingApi.stats,
  })
  const { data: claimStats } = useQuery({
    queryKey: claimKeys.stats(),
    queryFn: claimsApi.stats,
    enabled: isAdmin,
  })
  const { data: customerStats } = useQuery({
    queryKey: customerKeys.stats(),
    queryFn: customersApi.stats,
    enabled: isAdmin,
  })

  // Admin "Recent containers" table — a bounded visual sample. (Nigeria's
  // pipeline section fetches its own complete, stage-filtered list.)
  const containers = useRecentContainers(isAdmin).data?.data ?? []

  // Nigeria ops action queues (6.1, P2-5) — all non-fatal, degrade to hidden/—.
  const pendingPls = usePendingPackingLists(isNigeria).data?.data ?? []
  const manifests = usePendingManifests(isNigeria).data?.data
  // "Awaiting verification" only bites once the container has reached Nigeria (B11 predicate).
  const pendingManifests = useMemo(
    () => (manifests ?? []).filter((m) => m.container_status && ARRIVED_IN_NG.has(m.container_status)),
    [manifests],
  )
  const openDisputes = useOpenDisputes(isNigeria).data?.data ?? []
  // Bottom two-column: money to collect (oldest outstanding) + goods to release.
  const outstanding = useOutstandingBilling(isNigeria).data?.data ?? []
  // One read drives both the "Ready for pickup" stat count and the list.
  const activeNotes = useActiveReleaseNotes(isNigeria).data?.data
  const awaitingPickup = activeNotes ?? []
  const readyForPickup = activeNotes ? activeNotes.length : null

  const firstName = session?.name?.split(' ')[0] ?? 'team'
  const customsAwaiting = (containerStats?.customs_clearance ?? 0) + (containerStats?.arrived ?? 0)
  const summaryLine =
    `${containerStats?.in_transit ?? 0} in transit · ${customsAwaiting} awaiting customs · ${containerStats?.at_warehouse ?? 0} ready for pickup`

  return (
    <div>
      {/* Greeting hero — prototype 3.1 */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--color-primary)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', marginBottom: 'var(--space-1)' }}>
          {greeting()}
        </div>
        <h1 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-2xl)', color: 'var(--color-ink)', margin: 0, letterSpacing: 'var(--tracking-tight)', lineHeight: 'var(--leading-tight)' }}>
          Lead every shipment, {firstName}.
        </h1>
        <p style={{ fontSize: 'var(--text-md)', color: 'var(--color-ink-3)', margin: 'var(--space-2) 0 0' }}>{summaryLine}</p>
      </div>

      {/* Headline + financial KPIs. The per-stage operational counts
          (in transit / arrived / customs / at warehouse …) live in the
          Container pipeline rail below, so they're not duplicated here. */}
      <div className={styles.statsRow}>
        <StatCard label="Containers" value={containerStats?.total ?? '—'} icon="container" />
        {isNigeria && (
          <StatCard
            label="Ready for pickup"
            value={readyForPickup ?? '—'}
            icon="package"
            sublabel="active release notes"
            accentColor="var(--color-primary)"
          />
        )}
        <StatCard label="Unpaid billing" value={billingStats?.unpaid ?? '—'} icon="coin" />
        <StatCard
          label="Outstanding"
          value={billingStats ? formatNgnCompact(billingStats.outstanding_ngn) : '—'}
          icon="coin"
          sublabel="unpaid + partial"
        />
        {isAdmin && <StatCard label="Active customers" value={customerStats?.active ?? '—'} icon="users" />}
        {isAdmin && <StatCard label="Open claims" value={claimStats?.open ?? '—'} icon="warn" sublabel={claimStats?.open ? 'needs attention' : 'no active disputes'} />}
      </div>

      <UnbilledQueue />

      {isNigeria && (
        <div style={{ marginTop: 'var(--space-2)', marginBottom: 'var(--space-5)' }}>
          <ContainerPipeline counts={containerStats} />
          {pendingPls.length > 0 && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <Card padding="none">
                <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
                  <SectionHead
                    title="Packing lists awaiting approval"
                    sub={`${pendingPls.length} submitted`}
                    action={<Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate('/packing-lists?status=pending_approval')}>Review all</Button>}
                  />
                </div>
                <Table
                  dense
                  cardBreakpoint={600}
                  columns={[{ title: 'Ref', type: 'reference' }, { title: 'Customer' }, { title: 'Cartons', type: 'number' }, { title: 'Status', type: 'status' }]}
                  rows={pendingPls.map((pl) => ({
                    onOpen: () => navigate(`/packing-lists/${pl.id}`),
                    cells: [
                      <Mono key="ref">{pl.reference ?? pl.id.slice(0, 8)}</Mono>,
                      <UserCell key="cust" name={pl.customer_name ?? '—'} email="" />,
                      <Mono key="cartons">{pl.carton_count}</Mono>,
                      <StatusBadge key="status" kind="packingList" status={pl.status} />,
                    ],
                  }))}
                />
              </Card>
            </div>
          )}

          {/* 6.1 action queues (P2-5) — only render when there's work to do */}
          {pendingManifests.length > 0 && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <Card padding="none">
                <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
                  <SectionHead
                    title="Containers awaiting manifest verification"
                    sub={`${pendingManifests.length} arrived in Nigeria, manifest still pending — blocks billing + release`}
                    action={<Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate('/manifests?status=pending')}>Verify</Button>}
                  />
                </div>
                <Table
                  dense
                  cardBreakpoint={600}
                  columns={[{ title: 'Container', type: 'reference' }, { title: 'Container status', type: 'status' }, { title: 'Cartons', type: 'number' }]}
                  rows={pendingManifests.slice(0, 6).map((m) => ({
                    onOpen: () => navigate(`/manifests/${m.id}`),
                    cells: [
                      <Mono key="num">{m.container_number ?? '—'}</Mono>,
                      <StatusBadge key="status" kind="container" status={m.container_status ?? ''} />,
                      <Mono key="cartons">{m.total_cartons}</Mono>,
                    ],
                  }))}
                />
              </Card>
            </div>
          )}

          {openDisputes.length > 0 && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <Card padding="none">
                <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
                  <SectionHead
                    title="CBM disputes need response"
                    sub={`${openDisputes.length} submitted — 24h acknowledge SLA`}
                    action={<Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate('/billing/disputes?status=submitted')}>Respond</Button>}
                  />
                </div>
                <Table
                  dense
                  cardBreakpoint={600}
                  columns={[{ title: 'Submitted', type: 'date' }, { title: 'Original (CBM)', type: 'number' }, { title: 'Status', type: 'status' }]}
                  rows={openDisputes.slice(0, 5).map((d) => ({
                    onOpen: () => navigate(`/billing/${d.billing_id}`),
                    cells: [
                      <span key="when" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>{formatDate(d.submitted_at)}</span>,
                      <Mono key="cbm">{d.original_cbm ?? '—'}</Mono>,
                      <StatusBadge key="status" kind="dispute" status={d.status} />,
                    ],
                  }))}
                />
              </Card>
            </div>
          )}

          {/* Bottom two-column — what Nigeria ops chases: money in + goods out. */}
          <div className={styles.dashGrid2} style={{ marginTop: 'var(--space-4)' }}>
            {outstanding.length > 0 && (
              <Card padding="none">
                <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
                  <SectionHead
                    title="Outstanding invoices"
                    sub="Oldest unpaid first — chase these before storage fees mount"
                    action={<Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate('/billing')}>View all</Button>}
                  />
                </div>
                <Table
                  dense
                  cardBreakpoint={420}
                  columns={[{ title: 'Customer' }, { title: 'Container', type: 'reference' }, { title: 'Outstanding (₦)', type: 'money' }]}
                  rows={outstanding.map((b) => ({
                    onOpen: () => navigate(`/billing/${b.id}`),
                    cells: [
                      <UserCell key="cust" name={b.customer_name ?? '—'} email="" />,
                      <Mono key="ctn">{b.container_number ?? '—'}</Mono>,
                      <Mono key="out" color="var(--color-error)">{formatNgn(b.outstanding_ngn)}</Mono>,
                    ],
                  }))}
                />
              </Card>
            )}
            {awaitingPickup.length > 0 && (
              <Card padding="none">
                <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
                  <SectionHead
                    title="Awaiting pickup"
                    sub="Released — not yet collected by the customer"
                    action={<Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate('/release-notes')}>View all</Button>}
                  />
                </div>
                <Table
                  dense
                  cardBreakpoint={420}
                  columns={[{ title: 'Customer' }, { title: 'Container', type: 'reference' }, { title: 'Cartons', type: 'number' }, { title: 'Status', type: 'status' }]}
                  rows={awaitingPickup.slice(0, 6).map((n) => ({
                    onOpen: () => navigate(`/release-notes/${n.id}`),
                    cells: [
                      <UserCell key="cust" name={n.customer_name ?? '—'} email="" />,
                      <Mono key="ctn">{n.container_number ?? '—'}</Mono>,
                      <Mono key="ctns">{n.total_cartons_for_customer}</Mono>,
                      n.is_on_credit
                        ? <Badge key="st" variant="warning">On credit</Badge>
                        : <Badge key="st" variant="info">Ready</Badge>,
                    ],
                  }))}
                />
              </Card>
            )}
          </div>
        </div>
      )}

      {/* 3.1 two-column main — Recent containers (left) + Activity feed (right) */}
      {isAdmin && (
        <div className={styles.dashCols} style={{ marginBottom: 'var(--space-5)' }}>
          <Card padding="none">
            <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
              <SectionHead
                title="Recent containers"
                sub="Latest across all stages"
                action={<Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate('/containers')}>View all</Button>}
              />
            </div>
            <Table
              dense
              cardBreakpoint={600}
              columns={[
                { title: 'Container', type: 'reference' },
                { title: 'Status', type: 'status' },
                { title: 'ETA', type: 'date' },
              ]}
              rows={containers.slice(0, 6).map((c) => ({
                onOpen: () => navigate(`/containers/${c.id}`),
                cells: [
                  <div key="num">
                    <Mono>{c.container_number}</Mono>
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginTop: 'var(--space-0-5)' }}>
                      {c.vessel_name ?? c.origin}
                    </div>
                  </div>,
                  <StatusBadge key="status" kind="container" status={c.status} />,
                  <span key="eta" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>{formatDate(c.estimated_arrival_date)}</span>,
                ],
              }))}
              emptyState={<EmptyState compact title="No containers yet" />}
            />
          </Card>
          <Card padding="none">
            <div style={{ padding: 'var(--space-5) var(--space-5) var(--space-1)' }}>
              <SectionHead title="Activity" sub="Recent across your tenant" />
            </div>
            <div style={{ padding: '0 var(--space-5) var(--space-3)' }}>
              <ActivityFeed limit={8} />
            </div>
          </Card>
        </div>
      )}

      {/* 3.1 bottom row — plan usage (staff-logins slot: no last_login field) + quick actions */}
      {isAdmin && (
        <div className={styles.dashCols}>
          <PlanUsagePanel />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
            <SectionHead title="Quick actions" />
            <QuickActionCard
              icon="plus"
              title="Add customer"
              sub="Onboard a new shipping customer"
              cta="Add customer"
              onAction={() => navigate('/admin/customers', { state: { openAdd: true } })}
            />
            <QuickActionCard
              icon="users"
              title="Invite staff"
              sub="Provision a China, Nigeria, or warehouse account"
              cta="Invite staff"
              accent
              onAction={() => navigate('/admin/users', { state: { openInvite: true } })}
            />
            <QuickActionCard
              icon="coin"
              title="Update dollar rate"
              sub="Set today's USD → NGN conversion rate"
              cta="Update rate"
              onAction={() => navigate('/admin/config/dollar-rate')}
            />
          </div>
        </div>
      )}
    </div>
  )
}
