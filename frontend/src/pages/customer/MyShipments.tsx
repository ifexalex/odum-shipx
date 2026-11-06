import { useEffect, useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { billingApi, type Billing } from '../../api/billing'
import { packingListApi, type PackingList } from '../../api/packingList'
import { Badge, Banner, Button, Card, Icon, Mono, Table, ViewLink } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import { useSession } from '../../auth/useSession'
import { CustomerStepper } from './CustomerStepper'
import styles from './MyShipments.module.css'

const ACTIVE_STATUSES = new Set([
  'loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance', 'cleared', 'at_warehouse',
])

const CONTAINER_STATUS_BADGE: Record<string, { label: string; variant: 'info' | 'warning' | 'success' | 'neutral' }> = {
  loading:           { label: 'Packing',     variant: 'info' },
  sealed:            { label: 'Packed',      variant: 'info' },
  in_transit:        { label: 'In transit',  variant: 'info' },
  arrived:           { label: 'Arrived NG',  variant: 'warning' },
  customs_clearance: { label: 'Customs',     variant: 'warning' },
  cleared:           { label: 'Cleared',     variant: 'success' },
  at_warehouse:      { label: 'Ready',       variant: 'success' },
  fully_released:    { label: 'Delivered',   variant: 'success' },
}

function fmtNgn(val: string | number | null | undefined): string {
  if (val == null) return '—'
  const n = Number(val)
  return `₦${n.toLocaleString('en-NG', { maximumFractionDigits: 0 })}`
}

function CustStat({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-ink-4)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 20, color: color ?? 'var(--color-ink)', marginTop: 2, letterSpacing: '-0.01em' }}>
        {value}
      </div>
    </div>
  )
}

export function MyShipments(): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()
  const [shipments, setShipments] = useState<PackingList[]>([])
  const [billing, setBilling] = useState<Billing[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hand-rolled fetch effect; migrate to TanStack Query (master plan 7.150)
    setLoading(true)
    setError(null)

    async function loadAll(): Promise<void> {
      try {
        const [plResult, billingResult] = await Promise.allSettled([
          packingListApi.list({ limit: 100 }),
          session?.userId ? billingApi.listForCustomer(session.userId) : Promise.resolve([]),
        ])
        if (!active) return
        if (plResult.status === 'fulfilled') setShipments(plResult.value.data)
        else throw plResult.reason
        if (billingResult.status === 'fulfilled') {
          const b = billingResult.value
          setBilling(Array.isArray(b) ? b : [])
        }
      } catch (err) {
        if (active) setError(err instanceof ApiError ? err.message : 'Could not load your shipments.')
      } finally {
        if (active) setLoading(false)
      }
    }
    void loadAll()
    return () => { active = false }
  }, [session?.userId])

  // Split into active and past
  const { active: activeShipments, past: pastShipments } = useMemo(() => {
    const active = shipments.filter((pl) => pl.container_status && ACTIVE_STATUSES.has(pl.container_status))
    const past = shipments.filter((pl) => pl.container_status === 'fully_released' || pl.container_status === 'cancelled')
    return { active, past }
  }, [shipments])

  // Stats for greeting
  const outstandingTotal = useMemo(
    () => billing.reduce((sum, b) => sum + Number(b.outstanding_ngn ?? 0), 0),
    [billing],
  )

  // Billing lookup by container_id for the active card
  const billingByContainer = useMemo(() => {
    const map = new Map<string, Billing>()
    for (const b of billing) map.set(b.container_id, b)
    return map
  }, [billing])

  const name = session?.name?.split(' ')[0] ?? 'there'

  if (loading) {
    return <div style={{ padding: 32, color: 'var(--color-ink-4)' }}>Loading your shipments…</div>
  }

  return (
    <div className={styles.page}>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      {/* Greeting */}
      <div className={styles.greeting}>
        <div className={styles.greetingEyebrow}>My shipments</div>
        <h2 className={styles.greetingTitle}>
          Hello {name} 👋
          {activeShipments.length === 1
            ? ' — your shipment is moving.'
            : activeShipments.length > 1
              ? ` — ${activeShipments.length} shipments on the way.`
              : ' — no active shipments right now.'}
        </h2>
        <p className={styles.greetingSub}>
          {activeShipments.length} active
          {' · '}
          {pastShipments.length} completed
          {outstandingTotal > 0 && ` · ${fmtNgn(outstandingTotal)} outstanding balance to settle`}
        </p>
      </div>

      {/* Active shipments — every shipment still in transit, not just the most recent */}
      {activeShipments.length > 0 && (
        <>
          <SectionHead
            title={activeShipments.length === 1 ? 'Active shipment' : `Active shipments (${activeShipments.length})`}
            sub={activeShipments.length === 1 ? 'In transit and getting closer' : 'Every shipment currently on its way'}
          />
          <div className={styles.sectionSpacer} />
          <div className={styles.activeList}>
            {activeShipments.map((shipment) => {
              const b = billingByContainer.get(shipment.container_id)
              const statusInfo = CONTAINER_STATUS_BADGE[shipment.container_status ?? '']
              return (
                <Card key={shipment.id} padding={0} style={{ overflow: 'hidden' }}>
                  <div className={styles.activeCardHeader}>
                    {/* Left — icon + reference + meta */}
                    <div className={styles.activeCardLeft}>
                      <div className={styles.shipIcon}>
                        <Icon name="ship" size={26} stroke={2} />
                      </div>
                      <div>
                        <div className={styles.activeCardRef}>
                          <Mono color="var(--color-ink)" style={{ fontSize: 16, fontWeight: 700 }}>
                            {shipment.reference ?? shipment.id.slice(0, 8)}
                          </Mono>
                          {statusInfo && (
                            <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
                          )}
                        </div>
                        <div className={styles.activeCardMeta}>
                          Container <Mono color="var(--color-ink-2)">{shipment.container_number ?? '—'}</Mono>
                          {shipment.vessel_name && (
                            <> · {shipment.vessel_name}{shipment.voyage_number && ` · Voy ${shipment.voyage_number}`}</>
                          )}
                        </div>
                      </div>
                    </div>
                    {/* Right — ETA */}
                    {shipment.container_eta && (
                      <div className={styles.activeCardEta}>
                        <div className={styles.etaLabel}>Expected arrival</div>
                        <div className={styles.etaDate}>
                          {new Date(shipment.container_eta).toLocaleDateString('en-GB', {
                            day: 'numeric', month: 'short', year: 'numeric',
                          })}
                        </div>
                        <div className={styles.etaSub}>Tin Can Port, Lagos</div>
                      </div>
                    )}
                  </div>

                  {/* Stepper */}
                  <div className={styles.stepperWrap}>
                    <CustomerStepper containerStatus={shipment.container_status ?? null} />
                  </div>

                  {/* Stats row + CTA */}
                  <div className={styles.activeCardFooter}>
                    <div className={styles.footerStats}>
                      <CustStat label="Cartons" value={String(shipment.carton_count)} />
                      <CustStat label="CBM" value={Number(shipment.total_cbm ?? 0).toFixed(3)} />
                      <CustStat
                        label="Total cost"
                        value={b ? fmtNgn(b.total_due_ngn) : '—'}
                        color={b ? 'var(--color-warning)' : undefined}
                      />
                      <CustStat
                        label="Outstanding"
                        value={b && Number(b.outstanding_ngn) > 0 ? fmtNgn(b.outstanding_ngn) : '—'}
                        color={b && Number(b.outstanding_ngn) > 0 ? 'var(--color-error)' : undefined}
                      />
                    </div>
                    <Button
                      className={styles.footerCta}
                      variant="primary"
                      icon="arrowright"
                      onClick={() => navigate(`/my-shipments/${shipment.id}`)}
                    >
                      View details
                    </Button>
                  </div>
                </Card>
              )
            })}
          </div>
        </>
      )}

      {/* Past shipments table */}
      {pastShipments.length > 0 && (
        <>
          <SectionHead
            title="Past shipments"
            sub={`Your previous ${pastShipments.length} deliveries`}
          />
          <div className={styles.sectionSpacer} />
          <Card padding={0}>
            <Table
              columns={[
                { title: 'Tracking code' },
                { title: 'Container' },
                { title: 'Status' },
                { title: 'Cartons', align: 'right' },
                { title: 'Delivered' },
                { title: 'Amount paid', align: 'right' },
                { title: '', width: '60px' },
              ]}
              rows={pastShipments.map((pl) => {
                const b = billingByContainer.get(pl.container_id)
                return {
                  cells: [
                    <Mono key="ref">{pl.reference ?? pl.id.slice(0, 8)}</Mono>,
                    <Mono key="ctn">{pl.container_number ?? '—'}</Mono>,
                    <Badge key="status" variant="success">Delivered</Badge>,
                    <Mono key="cartons">{pl.carton_count}</Mono>,
                    <span key="date" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
                      {new Date(pl.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </span>,
                    <Mono key="paid">{b ? fmtNgn(b.total_paid_ngn) : '—'}</Mono>,
                    <ViewLink key="view" onClick={() => navigate(`/my-shipments/${pl.id}`)} />,
                  ],
                }
              })}
            />
          </Card>
        </>
      )}

      {/* Empty state */}
      {shipments.length === 0 && !loading && (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>No shipments yet</p>
          <p style={{ color: 'var(--color-ink-3)', fontSize: 14 }}>
            Your cargo will appear here once your packing list has been approved.
          </p>
        </div>
      )}
    </div>
  )
}
