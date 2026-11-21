import { useQuery } from '@tanstack/react-query'
import { useMemo, type JSX } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { billingApi, type Billing } from '../../api/billing'
import { billingKeys, packingListKeys } from '../../api/keys'
import { packingListApi } from '../../api/packingList'
import { STALE_30S } from '../../lib/queryClient'
import { Banner, Card, Icon, Mono, Table, StatusBadge, PageSkeleton } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import { useSession } from '../../auth/useSession'
import { CustomerStepper } from './CustomerStepper'
import styles from './MyShipments.module.css'
import { formatCbm, formatDate, formatNgn, todayIso } from '../../lib/format'
import { activeSummary, arrivalLabel, shipmentStage } from './shipmentStage'
import { PageHeader } from '../../shell/PageHeader'

function fmtNgn(val: string | number | null | undefined): string {
  return formatNgn(val)
}

// Money is ink; only an amount still owed is red (FD-27). The total cost was amber, with no meaning behind it.
function CustStat({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div>
      <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--color-ink-4)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)' }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-xl)', color: color ?? 'var(--color-ink)', marginTop: 'var(--space-0-5)', letterSpacing: 'var(--tracking-tight)' }}>
        {value}
      </div>
    </div>
  )
}

export function MyShipments(): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()

  const shipmentParams = { limit: 100 }
  const { data: shipmentPage, isLoading: loading, error: loadError } = useQuery({
    queryKey: packingListKeys.lookup(shipmentParams),
    queryFn: () => packingListApi.list(shipmentParams),
    staleTime: STALE_30S,
  })
  const shipments = shipmentPage?.data ?? []

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load your shipments.'
    : null

  // Ground-truth bug found while migrating this page (7.150): the billing half
  // used to call `billingApi.listForCustomer(session.userId)`. That endpoint
  // takes a *customer* id, and the backend compares it against the customer row
  // resolved from the caller's user_id — two different values — so it returned
  // **403 on every call**, verified live. Because the old code fetched it under
  // Promise.allSettled and treated billing as non-fatal, the failure was
  // swallowed: `billing` was always `[]`, which silently meant the outstanding
  // -balance greeting always read ₦0 and the per-shipment billing lookup below
  // never resolved anything. Fixed by using GET /v1/billing, which the backend
  // force-scopes to the caller's own customer_id — the same call the sibling
  // MyShipmentDetail already made correctly.
  //
  // Still non-fatal: the page renders without billing, so this query's error is
  // deliberately not surfaced.
  const { data: billingPage } = useQuery({
    queryKey: billingKeys.lookup({}),
    queryFn: () => billingApi.list(),
    staleTime: STALE_30S,
  })
  const billing: Billing[] = billingPage?.data ?? []

  // Split into active and past
  const { active: activeShipments, past: pastShipments } = useMemo(() => {
    const active = shipments.filter((pl) => {
      const stage = shipmentStage(pl.container_status)
      return stage === 'in_transit' || stage === 'ready_for_pickup'
    })
    const past = shipments.filter((pl) => shipmentStage(pl.container_status) === 'complete')
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
  const today = todayIso()

  if (loading) {
    return <PageSkeleton kind="list" label="Loading your shipments" />
  }

  return (
    <div className={styles.page}>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      <PageHeader
        title="My shipments"
        meta={[
          `Hello ${name}`,
          // By stage, not "5 on the way" counting ones already waiting at the warehouse (FD-27).
          activeSummary(activeShipments.map((pl) => pl.container_status)),
          `${pastShipments.length} completed`,
          outstandingTotal > 0 && `${fmtNgn(outstandingTotal)} outstanding`,
        ]}
      />

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
              const arrival = arrivalLabel(shipment.container_status, shipment.container_eta, today)
              const owed = b ? Number(b.outstanding_ngn) : 0
              return (
                // The whole card opens the shipment (FD-27): the reference is a link stretched over the card, so
                // there is one link per card for a screen reader and no separate button.
                <div key={shipment.id} className={styles.activeCard}>
                  <Card padding="none" style={{ overflow: 'hidden' }}>
                  <div className={styles.activeCardHeader}>
                    {/* Left — icon + reference + meta */}
                    <div className={styles.activeCardLeft}>
                      <div className={styles.shipIcon}>
                        <Icon name="ship" size={26} stroke={2} />
                      </div>
                      <div>
                        <div className={styles.activeCardRef}>
                          <Link to={`/my-shipments/${shipment.id}`} className={styles.cardLink}>
                            <Mono color="var(--color-ink)" style={{ fontSize: 'var(--text-lg)', fontWeight: 700 }}>
                              {shipment.reference ?? shipment.id.slice(0, 8)}
                            </Mono>
                          </Link>
                          {shipment.container_status && (
                            <StatusBadge kind="container" status={shipment.container_status} audience="customer" />
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
                    {/* Right — arrival: expected, delayed or arrived, by the container's real stage */}
                    {arrival && (
                      <div className={styles.activeCardEta}>
                        {arrival.label === 'Expected arrival' ? (
                          <>
                            <div className={styles.etaLabel}>{arrival.label}</div>
                            <div className={styles.etaDate}>{arrival.detail}</div>
                          </>
                        ) : (
                          <>
                            <div className={styles.etaDate}>{arrival.label}</div>
                            {arrival.detail && <div className={styles.etaSub}>{arrival.detail}</div>}
                          </>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Stepper */}
                  <div className={styles.stepperWrap}>
                    <CustomerStepper containerStatus={shipment.container_status ?? null} />
                  </div>

                  {/* Stats row */}
                  <div className={styles.activeCardFooter}>
                    <div className={styles.footerStats}>
                      <CustStat label="Cartons" value={String(shipment.carton_count)} />
                      <CustStat label="CBM" value={formatCbm(shipment.total_cbm ?? 0)} />
                      <CustStat label="Total cost" value={b ? fmtNgn(b.total_due_ngn) : '—'} />
                      <CustStat
                        label="Outstanding"
                        value={owed > 0 ? fmtNgn(owed) : '—'}
                        color={owed > 0 ? 'var(--color-error)' : undefined}
                      />
                    </div>
                    <Icon name="chevright" size={20} color="var(--color-ink-4)" />
                  </div>
                  </Card>
                </div>
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
          <Card padding="none">
            <Table
              columns={[
                { title: 'Tracking code', type: 'reference' },
                { title: 'Container', type: 'reference' },
                { title: 'Status', type: 'status' },
                { title: 'Cartons', type: 'number' },
                // The packing list's own date: "Delivered" claimed a delivery date this is not (FD-27).
                { title: 'Booked', type: 'date' },
                { title: 'Amount paid (₦)', type: 'money' },
              ]}
              rows={pastShipments.map((pl) => {
                const b = billingByContainer.get(pl.container_id)
                return {
                  onOpen: () => navigate(`/my-shipments/${pl.id}`),
                  cells: [
                    <Mono key="ref">{pl.reference ?? pl.id.slice(0, 8)}</Mono>,
                    <Mono key="ctn">{pl.container_number ?? '—'}</Mono>,
                    <StatusBadge key="status" kind="container" status={pl.container_status ?? 'fully_released'} audience="customer" />,
                    <Mono key="cartons">{pl.carton_count}</Mono>,
                    <span key="date" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                      {formatDate(pl.created_at)}
                    </span>,
                    <Mono key="paid">{b ? fmtNgn(b.total_paid_ngn) : '—'}</Mono>,
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
          <p style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-md)' }}>
            Your cargo will appear here once your packing list has been approved.
          </p>
        </div>
      )}
    </div>
  )
}
