/**
 * Shared dashboard for tenant_admin and nigeria_office_staff.
 * Shows summary stats from billing and containers via existing APIs.
 */

import { useEffect, useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { billingApi, disputeApi, type CBMDispute, type RecentPayment } from '../../api/billing'
import { claimsApi } from '../../api/claims'
import { CONTAINER_STATUS_LABELS } from '../../api/containerRules'
import { manifestApi, type Manifest } from '../../api/manifest'
import { ARRIVED_IN_NG } from '../../api/manifestRules'
import { packingListApi, type PackingList } from '../../api/packingList'
import { releaseNotesApi } from '../../api/releaseNotes'
import { customersApi } from '../../api/tenantManagement'
import { containersApi, type Container, type ContainerStatus } from '../../api/tracking'
import { useSession } from '../../auth/useSession'
import { Badge, Button, Card, Mono, QuickActionCard, StatCard, Table, UserCell, type BadgeVariant } from '../../design/components'
import { ActivityFeed } from '../../shell/ActivityFeed'
import { PlanUsagePanel } from '../../shell/PlanUsagePanel'
import { SectionHead } from '../../shell/SectionHead'
import styles from './admin.module.css'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

// 6.1 "Incoming containers" ETA chip: Today / N days / N wks (prototype IncomingRow).
function etaLabel(iso: string | null | undefined): string {
  if (!iso) return '—'
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  if (days < 14) return `${days} days`
  return `${Math.round(days / 7)} wks`
}

// Containers still on their way to Nigeria, soonest ETA first.
const INCOMING_STATUSES = new Set(['sealed', 'in_transit'])

const CONTAINER_BADGE: Record<string, BadgeVariant> = {
  loading: 'neutral',
  sealed: 'info',
  in_transit: 'info',
  arrived: 'warning',
  customs_clearance: 'warning',
  cleared: 'primary',
  at_warehouse: 'primary',
  fully_released: 'success',
  cancelled: 'neutral',
}

// 6.1 — NgOps container pipeline kanban (prototype nigeria-screens.jsx PipelineKanban).
// One column per pipeline stage; cards navigate to the container.
const KANBAN_STAGES: ContainerStatus[] = [
  'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance', 'cleared', 'at_warehouse', 'fully_released',
]

function PipelineKanban({ containers, onOpen }: { containers: Container[]; onOpen: (id: string) => void }): JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 8 }}>
      {KANBAN_STAGES.map((stage) => {
        const items = containers.filter((c) => c.status === stage)
        return (
          <div key={stage} style={{ minWidth: 190, flex: '0 0 190px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 4px', marginBottom: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--color-ink-3)' }}>
                {CONTAINER_STATUS_LABELS[stage]}
              </span>
              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--color-ink-4)', background: 'var(--color-line-soft)', borderRadius: 999, padding: '1px 7px' }}>
                {items.length}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {items.slice(0, 6).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => onOpen(c.id)}
                  style={{
                    textAlign: 'left', cursor: 'pointer',
                    background: 'var(--color-surface)', border: '1px solid var(--color-line-soft)',
                    borderRadius: 10, padding: '10px 12px',
                    boxShadow: '0 1px 2px rgba(11,47,13,0.04)',
                    transition: 'transform .16s cubic-bezier(.2,.7,.3,1), box-shadow .16s, border-color .16s',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 2px 6px rgba(11,47,13,0.08), 0 10px 24px -8px rgba(11,47,13,0.18)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = '0 1px 2px rgba(11,47,13,0.04)' }}
                >
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, fontWeight: 600, color: 'var(--color-ink)' }}>{c.container_number}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-ink-4)', marginTop: 3 }}>
                    {c.estimated_arrival_date ? `ETA ${c.estimated_arrival_date.slice(0, 10)}` : c.origin}
                  </div>
                </button>
              ))}
              {items.length > 6 && (
                <span style={{ fontSize: 11, color: 'var(--color-ink-4)', padding: '2px 4px' }}>+{items.length - 6} more</span>
              )}
              {items.length === 0 && (
                <div style={{ border: '1px dashed var(--color-line)', borderRadius: 10, padding: '12px 10px', fontSize: 11, color: 'var(--color-ink-4)', textAlign: 'center' }}>
                  Empty
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function Dashboard(): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()
  const [containerCount, setContainerCount] = useState<number | null>(null)
  const [unpaidCount, setUnpaidCount] = useState<number | null>(null)
  const [pendingBillingNgn, setPendingBillingNgn] = useState<number | null>(null)
  const [containers, setContainers] = useState<Container[]>([])
  const [pendingPls, setPendingPls] = useState<PackingList[]>([])
  const [customerCount, setCustomerCount] = useState<number | null>(null)
  const [openClaims, setOpenClaims] = useState<number | null>(null)
  // Nigeria ops action queues (6.1, P2-5)
  const [pendingManifests, setPendingManifests] = useState<Manifest[]>([])
  const [openDisputes, setOpenDisputes] = useState<CBMDispute[]>([])
  const [recentPayments, setRecentPayments] = useState<RecentPayment[]>([])
  const [readyForPickup, setReadyForPickup] = useState<number | null>(null)

  const isAdmin = session?.role === 'tenant_admin'
  const isNigeria = session?.role === 'nigeria_office_staff'

  useEffect(() => {
    void (async () => {
      try {
        const [containersResult, billing] = await Promise.all([
          containersApi.list({}),
          billingApi.list({ status: 'unpaid' }),
        ])
        setContainers(containersResult.data)
        setContainerCount(containersResult.data.length)
        setUnpaidCount(billing.data.length)
        const totalPending = billing.data.reduce((sum, b) => sum + Number(b.outstanding_ngn), 0)
        setPendingBillingNgn(totalPending)
      } catch {
        // Non-fatal — stats are informational
      }
    })()
  }, [])

  // Admin-only extra stats (prototype 3.1) — non-fatal, degrade to "—".
  useEffect(() => {
    if (!isAdmin) return
    void customersApi.list({ limit: 1 })
      .then((r) => setCustomerCount(r.meta.pagination.total_count ?? r.data.length))
      .catch(() => setCustomerCount(null))
    void claimsApi.list({ limit: 100 })
      .then((r) => setOpenClaims(r.data.filter((c) => c.status === 'filed' || c.status === 'under_inspection').length))
      .catch(() => setOpenClaims(null))
  }, [isAdmin])

  // Container-status breakdown for the greeting summary line.
  const summary = useMemo(() => {
    const inTransit = containers.filter((c) => c.status === 'in_transit').length
    const customs = containers.filter((c) => c.status === 'customs_clearance' || c.status === 'arrived').length
    const ready = containers.filter((c) => c.status === 'at_warehouse').length
    return { inTransit, customs, ready }
  }, [containers])

  // 6.1 "Incoming containers" — still at sea, soonest ETA first (no-ETA rows last).
  const incoming = useMemo(
    () =>
      containers
        .filter((c) => INCOMING_STATUSES.has(c.status))
        .sort((a, b) => (a.estimated_arrival_date ?? '9999') < (b.estimated_arrival_date ?? '9999') ? -1 : 1)
        .slice(0, 5),
    [containers],
  )

  // Nigeria ops: packing-list approval queue (6.1)
  useEffect(() => {
    if (!isNigeria) return
    void (async () => {
      try {
        const result = await packingListApi.list({ status: 'submitted', limit: 10 })
        setPendingPls(result.data)
      } catch {
        // non-fatal
      }
    })()
  }, [isNigeria])

  // Nigeria ops action queues (6.1, P2-5) — all non-fatal, degrade to hidden/—.
  useEffect(() => {
    if (!isNigeria) return
    void manifestApi.list({ verification_status: 'pending', limit: 20 })
      // "Awaiting verification" only bites once the container has reached Nigeria (B11 predicate).
      .then((r) => setPendingManifests(r.data.filter((m) => m.container_status && ARRIVED_IN_NG.has(m.container_status))))
      .catch(() => setPendingManifests([]))
    void disputeApi.list({ status: 'submitted', limit: 10 })
      .then((r) => setOpenDisputes(r.data))
      .catch(() => setOpenDisputes([]))
    void billingApi.recentPayments(6)
      .then(setRecentPayments)
      .catch(() => setRecentPayments([]))
    void releaseNotesApi.list({ status: 'active', limit: 50 })
      .then((r) => setReadyForPickup(r.data.length))
      .catch(() => setReadyForPickup(null))
  }, [isNigeria])

  const firstName = session?.name?.split(' ')[0] ?? 'team'
  const summaryLine =
    `${summary.inTransit} in transit · ${summary.customs} awaiting customs · ${summary.ready} ready for pickup`

  return (
    <div>
      {/* Greeting hero — prototype 3.1 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--color-primary)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>
          {greeting()}
        </div>
        <h1 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 28, color: 'var(--color-ink)', margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15 }}>
          Lead every shipment, {firstName}.
        </h1>
        <p style={{ fontSize: 14, color: 'var(--color-ink-3)', margin: '6px 0 0' }}>{summaryLine}</p>
      </div>

      <div className={styles.statsRow}>
        <StatCard label="Containers" value={containerCount ?? '—'} icon="container" />
        <StatCard label="Unpaid billing" value={unpaidCount ?? '—'} icon="coin" />
        <StatCard
          label="Outstanding (₦)"
          value={pendingBillingNgn !== null ? `₦${pendingBillingNgn.toLocaleString()}` : '—'}
          icon="coin"
        />
        {isAdmin && <StatCard label="Active customers" value={customerCount ?? '—'} icon="users" />}
        {isAdmin && <StatCard label="Open claims" value={openClaims ?? '—'} icon="warn" sublabel={openClaims ? 'needs attention' : 'no active disputes'} />}
        {isNigeria && <StatCard label="Ready for pickup" value={readyForPickup ?? '—'} icon="package" sublabel="active release notes" />}
      </div>

      {isNigeria && (
        <div style={{ marginTop: 8, marginBottom: 20 }}>
          <Card padding={20}>
            <SectionHead title="Container pipeline" sub="Every container by stage — click a card to open it" />
            <div style={{ height: 12 }} />
            <PipelineKanban containers={containers.filter((c) => c.status !== 'cancelled')} onOpen={(id) => navigate(`/containers/${id}`)} />
          </Card>
          {pendingPls.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Card padding={0}>
                <div style={{ padding: '18px 20px' }}>
                  <SectionHead
                    title="Packing lists awaiting approval"
                    sub={`${pendingPls.length} submitted`}
                    action={<Button variant="secondary" size="sm" onClick={() => navigate('/packing-lists')}>Review all →</Button>}
                  />
                </div>
                <Table
                  dense
                  columns={[{ title: 'Ref' }, { title: 'Customer' }, { title: 'Cartons', align: 'right' }, { title: 'Status' }]}
                  rows={pendingPls.map((pl) => ({
                    cells: [
                      <Mono key="ref">{pl.reference ?? pl.id.slice(0, 8)}</Mono>,
                      <UserCell key="cust" name={pl.customer_name ?? '—'} email="" />,
                      <Mono key="cartons">{pl.carton_count}</Mono>,
                      <Badge key="status" variant="warning">Submitted</Badge>,
                    ],
                  }))}
                />
              </Card>
            </div>
          )}

          {/* 6.1 action queues (P2-5) — only render when there's work to do */}
          {pendingManifests.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Card padding={0}>
                <div style={{ padding: '18px 20px' }}>
                  <SectionHead
                    title="Containers awaiting manifest verification"
                    sub={`${pendingManifests.length} arrived in Nigeria, manifest still pending — blocks billing + release`}
                    action={<Button variant="secondary" size="sm" onClick={() => navigate('/manifests')}>Verify →</Button>}
                  />
                </div>
                <Table
                  dense
                  columns={[{ title: 'Container' }, { title: 'Container status' }, { title: 'Cartons', align: 'right' }, { title: '', width: '60px' }]}
                  rows={pendingManifests.slice(0, 6).map((m) => ({
                    cells: [
                      <Mono key="num">{m.container_number ?? '—'}</Mono>,
                      <Badge key="status" variant={CONTAINER_BADGE[m.container_status ?? ''] ?? 'neutral'}>
                        {CONTAINER_STATUS_LABELS[m.container_status as ContainerStatus] ?? m.container_status}
                      </Badge>,
                      <Mono key="cartons">{m.total_cartons}</Mono>,
                      <Button key="view" variant="ghost" size="sm" onClick={() => navigate(`/manifests/${m.id}`)}>View</Button>,
                    ],
                  }))}
                />
              </Card>
            </div>
          )}

          {openDisputes.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Card padding={0}>
                <div style={{ padding: '18px 20px' }}>
                  <SectionHead
                    title="CBM disputes need response"
                    sub={`${openDisputes.length} submitted — 24h acknowledge SLA`}
                    action={<Button variant="secondary" size="sm" onClick={() => navigate('/billing/disputes')}>Respond →</Button>}
                  />
                </div>
                <Table
                  dense
                  columns={[{ title: 'Submitted' }, { title: 'Original CBM', align: 'right' }, { title: 'Status' }]}
                  rows={openDisputes.slice(0, 5).map((d) => ({
                    cells: [
                      <span key="when" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{d.submitted_at.slice(0, 10)}</span>,
                      <Mono key="cbm">{d.original_cbm ?? '—'}</Mono>,
                      <Badge key="status" variant="warning">Submitted</Badge>,
                    ],
                  }))}
                />
              </Card>
            </div>
          )}

          {/* 6.1 bottom two-column — Recent payments + Incoming containers */}
          <div className={styles.dashGrid2} style={{ marginTop: 16 }}>
            {recentPayments.length > 0 && (
              <Card padding={0}>
                <div style={{ padding: '18px 20px' }}>
                  <SectionHead
                    title="Recent payments"
                    sub="Latest confirmed across all billings"
                    action={<Button variant="secondary" size="sm" onClick={() => navigate('/billing')}>View all →</Button>}
                  />
                </div>
                <Table
                  dense
                  columns={[{ title: 'Customer' }, { title: 'Amount (₦)', align: 'right' }, { title: 'Method' }, { title: 'Date' }]}
                  rows={recentPayments.map((p) => ({
                    cells: [
                      <UserCell key="cust" name={p.customer_name ?? '—'} email="" />,
                      <Mono key="amt">₦{Number(p.amount_ngn).toLocaleString()}</Mono>,
                      <span key="method" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{p.payment_method?.replace(/_/g, ' ') ?? '—'}</span>,
                      <span key="date" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{p.payment_date ?? p.created_at.slice(0, 10)}</span>,
                    ],
                  }))}
                />
              </Card>
            )}
            {incoming.length > 0 && (
              <Card padding={0}>
                <div style={{ padding: '18px 20px' }}>
                  <SectionHead
                    title="Incoming containers"
                    sub={`Next ${incoming.length} expected arrival${incoming.length === 1 ? '' : 's'}`}
                    action={<Button variant="secondary" size="sm" onClick={() => navigate('/containers')}>View all →</Button>}
                  />
                </div>
                <div style={{ padding: '0 20px 16px' }}>
                  {incoming.map((c, i) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => navigate(`/containers/${c.id}`)}
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                        width: '100%', textAlign: 'left', padding: '10px 0', cursor: 'pointer',
                        background: 'none', border: 0,
                        borderTop: i > 0 ? '1px solid var(--color-line-soft)' : 'none',
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <Mono>{c.container_number}</Mono>
                        <div style={{ fontSize: 11, color: 'var(--color-ink-4)', marginTop: 2 }}>
                          {c.vessel_name ?? c.origin}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right', flexShrink: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-ink)' }}>{etaLabel(c.estimated_arrival_date)}</div>
                        <div style={{ fontSize: 11, color: 'var(--color-ink-4)', marginTop: 2 }}>
                          {c.estimated_arrival_date?.slice(0, 10) ?? 'ETA unknown'}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* 3.1 two-column main — Recent containers (left) + Activity feed (right) */}
      {isAdmin && (
        <div className={styles.dashCols} style={{ marginBottom: 20 }}>
          <Card padding={0}>
            <div style={{ padding: '18px 20px' }}>
              <SectionHead
                title="Recent containers"
                sub="Latest across all stages"
                action={<Button variant="secondary" size="sm" onClick={() => navigate('/containers')}>View all →</Button>}
              />
            </div>
            <Table
              dense
              columns={[
                { title: 'Container' },
                { title: 'Status' },
                { title: 'ETA' },
                { title: '', width: '60px' },
              ]}
              rows={containers.slice(0, 6).map((c) => ({
                cells: [
                  <div key="num">
                    <Mono>{c.container_number}</Mono>
                    <div style={{ fontSize: 11, color: 'var(--color-ink-4)', marginTop: 2 }}>
                      {c.vessel_name ?? c.origin}
                    </div>
                  </div>,
                  <Badge key="status" variant={CONTAINER_BADGE[c.status] ?? 'neutral'}>
                    {CONTAINER_STATUS_LABELS[c.status] ?? c.status}
                  </Badge>,
                  <span key="eta" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{c.estimated_arrival_date?.slice(0, 10) ?? '—'}</span>,
                  <Button key="view" variant="ghost" size="sm" onClick={() => navigate(`/containers/${c.id}`)}>View</Button>,
                ],
              }))}
              emptyState={<span>No containers yet.</span>}
            />
          </Card>
          <Card padding={0}>
            <div style={{ padding: '18px 20px 4px' }}>
              <SectionHead title="Activity" sub="Recent across your tenant" />
            </div>
            <div style={{ padding: '0 20px 12px' }}>
              <ActivityFeed limit={8} />
            </div>
          </Card>
        </div>
      )}

      {/* 3.1 bottom row — plan usage (staff-logins slot: no last_login field) + quick actions */}
      {isAdmin && (
        <div className={styles.dashCols}>
          <PlanUsagePanel />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
