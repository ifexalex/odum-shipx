/**
 * 10.2 — Customer Shipment Detail (audit gap A3, prototype customer-screens.jsx
 * CustomerShipmentDetail).
 *
 * Content zones per the prototype: hero (reference + status), tracking stepper,
 * my-cartons table, billing summary with pay CTA, and the file-a-claim prompt.
 * The prototype's Documents zone is deferred (AUDIT_GAPS.md — needs a
 * customer-visible document-scope decision).
 *
 * Data flow (ground-truth fix, 2026-07-12): a customer "shipment" is their
 * packing list. This page previously fetched /v1/track/{code} — a route that
 * doesn't exist anywhere (every load 404'd) and was keyed by packing-list
 * reference besides. Now: /my-shipments/:code carries the packing-list id →
 * GET /v1/packing-lists/{id} (customer-own enforced server-side) supplies the
 * cartons + container status; billing comes from the customer's own billing
 * list matched by container.
 */
import { useQuery } from '@tanstack/react-query'
import { useMemo, type JSX } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { billingApi, paymentClaimApi, type Billing } from '../../api/billing'
import { billingKeys, packingListKeys } from '../../api/keys'
import { packingListApi } from '../../api/packingList'
import { STALE_30S } from '../../lib/queryClient'
import { Banner, Button, Card, Icon, Kvp, Mono, StatusBadge, Table, LinesSkeleton, PageSkeleton, EmptyState } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import { CustomerStepper } from './CustomerStepper'
import { ReleaseNoteCard } from './ReleaseNoteCard'
import styles from './customer.module.css'
import { formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'

// Ground truth: api/tracking.ts's ContainerStatus (services/tracking + the
// `container` table) — the 9 real values. This map previously used fictional
// keys ('active', 'packed', 'arrived_ng', 'partially_released') that never
// matched a real container status, so every lookup fell through to the
// literal fallback string; combined with the detail endpoint not returning
// container_status at all (see repository.py fix), the badge always showed
// "Preparing" regardless of the container's actual state.
// Customer-friendly "where is it now" hint per status (prototype's green banner).
const STATUS_HINT: Record<string, string> = {
  loading: 'Your cartons are being received and packed at the China warehouse.',
  sealed: 'The container is sealed and awaiting vessel departure.',
  in_transit: "Your container is at sea. We'll notify you the moment it docks in Lagos.",
  arrived: 'The container has arrived in Nigeria and is queued for customs.',
  customs_clearance: 'Your container is going through customs clearance.',
  cleared: 'Customs cleared — the container is on its way to the warehouse.',
  at_warehouse: 'Your cargo is at the warehouse. Settle any outstanding balance to receive your release note.',
  fully_released: 'This shipment is complete. Thanks for shipping with us!',
}

function fmtNgn(value: number): string {
  return formatNgn(value)
}

export function MyShipmentDetail(): JSX.Element {
  const { code } = useParams<{ code: string }>()
  const navigate = useNavigate()
  const { data: pl = null, isLoading: loading, error: loadError } = useQuery({
    queryKey: packingListKeys.detail(code ?? ''),
    queryFn: () => packingListApi.get(code!),
    enabled: !!code,
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(pl?.reference ?? code)

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load this shipment.'
    : null

  // Billing is non-fatal — the page renders without it, so this query's error
  // is deliberately not surfaced.
  const { data: billingPage } = useQuery({
    queryKey: billingKeys.lookup({}),
    queryFn: () => billingApi.list(),
    staleTime: STALE_30S,
  })
  const billing: Billing[] | null = billingPage?.data ?? null

  // The billing record for this shipment's container (customer-scoped list).
  const shipmentBilling = useMemo(() => {
    if (!pl || !billing) return null
    return billing.find((b) => b.container_id === pl.container_id) ?? null
  }, [pl, billing])

  // A pending "I've made this payment" claim means the outstanding amount
  // may already be on its way — the Pay CTA must not invite a duplicate
  // payment while one is in flight (see MyBillingDetail.tsx's matching fix).
  // Keyed under billingKeys.detail(id) so it shares the slot MyBillingDetail
  // and the staff BillingDetail already use for the same billing's claims.
  const { data: paymentClaims = [] } = useQuery({
    queryKey: [...billingKeys.detail(shipmentBilling?.id ?? ''), 'payment-claims'],
    queryFn: () => paymentClaimApi.listForBilling(shipmentBilling!.id),
    enabled: !!shipmentBilling,
    staleTime: STALE_30S,
  })
  const pendingClaim = paymentClaims.find((c) => c.status === 'pending') ?? null

  if (loading) return <PageSkeleton kind="detail" label="Loading your shipment" />

  if (error || !pl) {
    return (
      <div className={styles.page}>
        <Banner variant="error">{error ?? 'Shipment not found.'}</Banner>
      </div>
    )
  }

  const status = pl.container_status ?? 'loading'
  const totalCbm = Number(pl.total_cbm)
  const outstanding = shipmentBilling ? Number(shipmentBilling.outstanding_ngn) : 0

  return (
    <div className={styles.page}>

      {/* Hero — prototype 10.2 */}
      <div className={styles.shipmentHero}>
        <div className={styles.shipmentHeroIcon}>
          <Icon name="ship" size={26} stroke={2} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div className={styles.shipmentHeroTitleRow}>
            <h1 className={styles.shipmentHeroCode}>{pl.reference ?? pl.id.slice(0, 8)}</h1>
            <StatusBadge kind="container" status={status} audience="customer" />
          </div>
          <div className={styles.shipmentHeroMeta}>
            {pl.container_number ? (
              <>
                Container <Mono color="var(--color-ink)">{pl.container_number}</Mono>
              </>
            ) : (
              'Awaiting container assignment'
            )}
            {' · '}
            {pl.carton_count} carton{pl.carton_count === 1 ? '' : 's'}
          </div>
        </div>
      </div>

      <ReleaseNoteCard containerId={pl.container_id} />

      {/* Tracking */}
      <Card padding="large">
        <SectionHead title="Tracking" sub="Where your cargo is right now" />
        <div style={{ height: 20 }} />
        <CustomerStepper containerStatus={pl.container_status ?? null} />
        {STATUS_HINT[status] && (
          <div className={styles.statusHint}>
            <Icon name="ship" size={18} color="var(--color-primary)" />
            <div className={styles.statusHintText}>{STATUS_HINT[status]}</div>
          </div>
        )}
      </Card>

      <div className={styles.detailGrid}>
        {/* My cartons */}
        <Card padding="none">
          <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
            <SectionHead
              title="My cartons"
              sub={`${pl.carton_count} carton${pl.carton_count === 1 ? '' : 's'} · ${totalCbm.toFixed(3)} CBM total`}
            />
          </div>
          <Table
            dense
            columns={[
              { title: 'Tag' },
              { title: 'Description' },
              { title: 'Weight', align: 'right' },
              { title: 'CBM', align: 'right' },
            ]}
            rows={pl.items.map((item) => ({
              cells: [
                <Mono key="tag">{item.carton_tag ?? item.tracking_code ?? '—'}</Mono>,
                <span key="desc" style={{ fontSize: 'var(--text-sm)' }}>{item.description}</span>,
                <Mono key="wt">
                  {item.weight_actual_kg ?? item.weight_dispatch_kg
                    ? `${Number(item.weight_actual_kg ?? item.weight_dispatch_kg).toFixed(1)} kg`
                    : '—'}
                </Mono>,
                <Mono key="cbm" color="var(--color-primary)">
                  {item.cbm ? Number(item.cbm).toFixed(3) : '—'}
                </Mono>,
              ],
            }))}
            emptyState={<EmptyState compact title="No cartons recorded yet" />}
          />
        </Card>

        {/* Billing summary */}
        <Card padding="default">
          <SectionHead
            title="Billing"
            action={
              shipmentBilling ? (
                <Link
                  to={`/my-billing/${shipmentBilling.id}`}
                  state={{ billing: shipmentBilling }}
                  className={styles.viewFullLink}
                >
                  View full invoice <Icon name="arrowright" size={12} />
                </Link>
              ) : undefined
            }
          />
          <div style={{ height: 8 }} />
          {billing === null && <LinesSkeleton label="Loading billing" />}
          {billing !== null && !shipmentBilling && (
            <p className={styles.billingNote}>
              No bill yet for this shipment — billing is generated when the container arrives and is measured.
            </p>
          )}
          {shipmentBilling && (
            <>
              <Kvp label="Shipping cost" value={<Mono>{fmtNgn(Number(shipmentBilling.subtotal_ngn))}</Mono>} />
              {/* Itemized by real description, not a lump "Misc fees" line —
                  see MyBillingDetail.tsx's matching fix and
                  frontend/07_domain_modules.md. */}
              {shipmentBilling.misc_fees.map((fee, i) => (
                <Kvp key={i} label={fee.description} value={<Mono>{fmtNgn(Number(fee.amount_ngn))}</Mono>} />
              ))}
              {Number(shipmentBilling.storage_fees_ngn) > 0 && (
                <Kvp label="Storage fees" value={<Mono>{fmtNgn(Number(shipmentBilling.storage_fees_ngn))}</Mono>} />
              )}
              <Kvp label="Total" value={<Mono>{fmtNgn(Number(shipmentBilling.total_due_ngn))}</Mono>} />
              <Kvp label="Paid" value={<Mono color="var(--color-success)">{fmtNgn(Number(shipmentBilling.total_paid_ngn))}</Mono>} />
              <Kvp
                label="Outstanding"
                value={
                  <Mono color={outstanding > 0 ? 'var(--color-error)' : 'var(--color-success)'}>
                    {fmtNgn(outstanding)}
                  </Mono>
                }
                divider={false}
              />
              {outstanding > 0 && pendingClaim && (
                <div className={styles.payCtaWrap}>
                  <Banner variant="warning" title="Payment submitted — awaiting confirmation">
                    You told us you sent {formatNgn(pendingClaim.amount_ngn)}. Staff will confirm
                    it shortly.
                  </Banner>
                </div>
              )}
              {outstanding > 0 && !pendingClaim && (
                <div className={styles.payCtaWrap}>
                  <Button
                    variant="accent"
                    full
                    icon="coin"
                    onClick={() => navigate(`/my-billing/${shipmentBilling.id}`, { state: { billing: shipmentBilling } })}
                  >
                    Pay outstanding
                  </Button>
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      {/* File a claim */}
      <div className={styles.claimPrompt}>
        <div className={styles.claimPromptIcon}>
          <Icon name="warn" size={18} stroke={2.2} />
        </div>
        <div style={{ flex: 1 }}>
          <div className={styles.claimPromptTitle}>Notice damage when your cargo arrives?</div>
          <div className={styles.claimPromptSub}>
            File a claim within 7 days of receiving your shipment — we inspect and respond quickly.
          </div>
        </div>
        <Button variant="secondary" size="sm" icon="plus" onClick={() => navigate('/my-claims/new')}>
          File a claim
        </Button>
      </div>
    </div>
  )
}
