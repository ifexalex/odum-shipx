import { useRef, useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { billingApi, disputeApi, paymentClaimApi, type Billing, type PaymentClaim } from '../../api/billing'
import { billingKeys } from '../../api/keys'
import { type BankTransferConfig } from '../../api/tenantManagement'
import { useBankTransferConfig } from '../../hooks/useConfig'
import { STALE_30S } from '../../lib/queryClient'
import { DialogGuard, Field, StatusBadge } from '../../design/components'
import { Badge, Banner, Button, Card, Kvp, Mono, StatCard } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import { EvidenceUploader, type UploadedEvidence } from '../nigeria/EvidenceUploader'
import { ReleaseNoteCard } from './ReleaseNoteCard'
import styles from './customer.module.css'
import { formatDate, formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'

// Bank details shown when customer selects manual transfer. Ground-truth gap
// found live: this used to be a single hardcoded account shown to every
// tenant's customers regardless of who they were actually paying — a real
// money-misdirection risk, not just an ambiguity. Now reads the tenant's own
// configured account (tenant-admin's PaymentGatewayConfig.tsx).
function BankTransferDetails({ config }: { config: BankTransferConfig | null }): JSX.Element {
  if (!config) {
    return (
      <Banner variant="warning" title="Bank details not available yet">
        Your shipping company hasn't set up bank transfer details yet. Contact them directly, or use
        "Pay online" if available.
      </Banner>
    )
  }
  return (
    <div className={styles.bankDetails}>
      <strong>Bank:</strong> {config.bank_name}<br />
      <strong>Account name:</strong> {config.account_name}<br />
      <strong>Account number:</strong> {config.account_number}<br />
      {config.sort_code && <><strong>Sort code:</strong> {config.sort_code}<br /></>}
      <br />
      <em>
        {config.instructions ?? 'Use your billing reference as the payment description.'} Once you've
        sent the transfer, use the button below to tell us and attach your receipt — staff can't confirm
        a payment they don't know about.
      </em>
    </div>
  )
}

// "I've made this payment" — the customer's manual-transfer confirmation,
// with mandatory evidence. Found live: this step didn't exist at all before
// — a customer had no way to tell the platform they'd paid, and staff had no
// queue and no proof, only whatever they happened to notice in the bank
// account.
//
// Only ever rendered when the caller (MyBillingDetail) has already
// confirmed there's no pending claim for this billing — a pending claim
// replaces this whole component with a top-level "awaiting confirmation"
// banner instead, and a rejected one shows its reason above the payment
// options rather than duplicating it in here. So this component is purely
// the submission form itself.
function PaymentClaimPanel({
  billingId,
  outstandingNgn,
  onSubmitted,
}: {
  billingId: string
  outstandingNgn: number
  onSubmitted: (claim: PaymentClaim) => void
}): JSX.Element {
  const idempotencyKey = useRef(crypto.randomUUID())
  const [showForm, setShowForm] = useState(false)
  const [amount, setAmount] = useState(String(outstandingNgn))
  const [note, setNote] = useState('')
  const [evidence, setEvidence] = useState<UploadedEvidence | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    if (!evidence || Number(amount) <= 0) return
    setSubmitting(true)
    setError(null)
    try {
      const claim = await paymentClaimApi.submit(
        billingId,
        {
          amount_ngn: Number(amount),
          evidence_file_key: evidence.file_key,
          evidence_file_name: evidence.filename,
          customer_note: note.trim() || undefined,
        },
        idempotencyKey.current,
      )
      onSubmitted(claim)
      setShowForm(false)
      setEvidence(null)
      setNote('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not submit your payment claim.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      {!showForm ? (
        <Button variant="secondary" onClick={() => setShowForm(true)}>
          I've made this payment
        </Button>
      ) : (
        <div className={styles.claimForm}>
          {error && <Banner variant="error" title="Could not submit">{error}</Banner>}
          <Field
            label="Amount transferred (₦)"
            name="claim_amount"
            type="number"
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <div>
            <label className={styles.selectLabel}>
              Evidence of payment
            </label>
            <p className={styles.cardHint}>
              A screenshot or photo of your transfer receipt — required before you can submit.
            </p>
            {evidence ? (
              <div className={styles.evidenceAttached}>
                <Badge variant="success">Attached</Badge> {evidence.filename}
                <Button variant="ghost" size="sm" onClick={() => setEvidence(null)}>
                  Remove
                </Button>
              </div>
            ) : (
              <EvidenceUploader
                getPresignedUrl={(f) => paymentClaimApi.getUploadUrl(billingId, f.name, f.type, f.size)}
                onUploaded={setEvidence}
              />
            )}
          </div>
          <Field
            label="Note"
            name="claim_note"
            multiline
            optional
            placeholder="e.g. Sent via GTBank mobile app"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className={styles.formActions}>
            <Button variant="ghost" onClick={() => { setShowForm(false); setEvidence(null); setError(null) }}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={submitting}
              disabled={!evidence || Number(amount) <= 0}
              onClick={() => void handleSubmit()}
            >
              Submit for review
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// 10.4 — CbmDisputeModal (customer-screens.jsx:574): the customer disputes the
// measured CBM with their own measurement + reason. One active dispute per
// billing (backend guard DISPUTE_ALREADY_OPEN).
function CbmDisputeModal({ billing, onCancel, onSuccess }: { billing: Billing; onCancel: () => void; onSuccess: () => void }): JSX.Element {
  const [measuredCbm, setMeasuredCbm] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = Number(measuredCbm) > 0 && reason.trim().length > 0 && !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      await disputeApi.file(billing.id, { disputed_cbm: measuredCbm, reason })
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not file the dispute.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className={styles.dialogOverlay}
      onClick={onCancel}
    >
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.dialogPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.dialogTitle}>Dispute the CBM measurement</h3>
        {error && <Banner variant="error" title="Could not file dispute">{error}</Banner>}
        <Banner variant="info" title={`We measured ${Number(billing.total_cbm).toFixed(3)} CBM`}>
          If your own measurement differs, file a dispute — our team acknowledges within 24 hours and
          re-measures. Your invoice is adjusted automatically if the correction is upheld.
        </Banner>
        <Field
          label="Your measured CBM"
          name="disputed_cbm"
          required
          type="number"
          placeholder={`e.g. ${Math.max(0, Number(billing.total_cbm) - 0.07).toFixed(2)}`}
          value={measuredCbm}
          onChange={(e) => setMeasuredCbm(e.target.value)}
        />
        <Field
          label="Why do you believe the measurement is wrong?"
          name="dispute_reason"
          required
          multiline
          placeholder="e.g. I measured the cartons at pickup and totalled 0.86 CBM…"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <div className={styles.dialogActions}>
          <Button variant="ghost" size="lg" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" size="lg" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            File dispute
          </Button>
        </div>
      </div>
    </div>
  )
}

export function MyBillingDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()

  // Router state from MyBilling seeds the first paint; the record itself lives
  // at billingKeys.detail(id), the same cache slot the staff BillingDetail uses,
  // so a mutation on either side is seen by both.
  const stateBilling = (location.state as { billing?: Billing } | null)?.billing ?? null
  const {
    data: billing = null,
    isLoading,
    error: loadError,
  } = useQuery({
    queryKey: billingKeys.detail(id ?? ''),
    queryFn: () => billingApi.get(id!),
    enabled: !!id,
    ...(stateBilling ? { initialData: stateBilling } : {}),
    staleTime: STALE_30S,
  })
  // Names this invoice in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(billing?.invoice_number)

  const [payLoading, setPayLoading] = useState(false)
  const [payError, setPayError] = useState<string | null>(null)
  const [invoiceLoading, setInvoiceLoading] = useState(false)
  const [invoiceError, setInvoiceError] = useState<string | null>(null)

  const { bankConfig } = useBankTransferConfig()

  const claimsKey = [...billingKeys.detail(id ?? ''), 'payment-claims']
  const { data: claims = [] } = useQuery({
    queryKey: claimsKey,
    queryFn: () => paymentClaimApi.listForBilling(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })

  // A customer who already submitted a claim (this session or a previous one)
  // should see its status without clicking "Show bank details" first. Derived
  // rather than pushed into state by an effect — the panel only ever opens.
  const [transferOpened, setTransferOpened] = useState(false)
  const showTransfer = transferOpened || claims.length > 0

  const error = loadError
    ? loadError instanceof ApiError && loadError.status === 404
      ? 'Billing record not found.'
      : loadError instanceof ApiError
        ? loadError.message
        : 'Could not load this billing record.'
    : null

  async function handleDownloadInvoice(): Promise<void> {
    if (!billing) return
    setInvoiceLoading(true)
    setInvoiceError(null)
    try {
      await billingApi.export(billing.id, 'pdf')
    } catch (err) {
      setInvoiceError(err instanceof ApiError ? err.message : 'Could not download the invoice. Try again.')
    } finally {
      setInvoiceLoading(false)
    }
  }

  // B12 — Paystack hosted checkout. The redirect is UX only; the webhook is
  // the source of truth, so PaymentSuccess honestly says "being confirmed".
  async function handlePayOnline(): Promise<void> {
    if (!billing) return
    setPayLoading(true)
    setPayError(null)
    try {
      const callbackUrl = `${window.location.origin}/my-billing/${billing.id}/payment-success`
      const result = await billingApi.initializePayment(billing.id, callbackUrl)
      window.location.assign(result.authorization_url)
    } catch (err) {
      setPayError(err instanceof ApiError ? err.message : 'Could not start the payment. Try again or use bank transfer.')
      setPayLoading(false)
    }
  }
  const [showDispute, setShowDispute] = useState(false)
  const [disputeFiled, setDisputeFiled] = useState(false)

  if (isLoading && !billing) return <div className={styles.loadingState}>Loading…</div>
  if (error && !billing) return (
    <div className={styles.page}>
      <Banner variant="error">{error ?? 'Not found.'}</Banner>
    </div>
  )
  if (!billing) return <></>

  const outstanding = Number(billing.outstanding_ngn)
  const isPaid = billing.payment_status === 'paid' || billing.payment_status === 'overpaid'
  const needsPayment = outstanding > 0 && !isPaid
  const pendingClaim = claims.find((c) => c.status === 'pending') ?? null
  const latestClaim = claims[0] ?? null

  return (
    <div className={styles.page}>
      <div className={styles.heroRow}>
        <div>
          <h1 className={styles.detailTitle}>{billing.container_number ?? billing.container_id}</h1>
          <div className={styles.claimStatusRow}>
            <StatusBadge kind="invoice" status={billing.payment_status} audience="customer" />
            {billing.billed_at && (
              <span className={styles.claimStatusText}>
                Billed {formatDate(billing.billed_at)}
              </span>
            )}
          </div>
        </div>
        <div className={styles.actionsWrap}>
          {billing._active_disputes.length === 0 && !disputeFiled && billing.payment_status !== 'cancelled' && (
            <Button variant="secondary" onClick={() => setShowDispute(true)}>
              Dispute CBM
            </Button>
          )}
          {needsPayment && (
            <Button
              variant="primary"
              onClick={() => navigate(`/my-billing/${billing.id}/refund-request`)}
            >
              Request refund
            </Button>
          )}
        </div>
      </div>

      <ReleaseNoteCard containerId={billing.container_id} />

      {(disputeFiled || billing._active_disputes.length > 0) && (
        <div className={styles.sectionGap}>
          <Banner variant="info" title="CBM dispute open">
            Your dispute is with our team — we acknowledge within 24 hours and re-measure. You&apos;ll be
            notified of the outcome.
          </Banner>
        </div>
      )}

      <div className={styles.statsRow}>
        <StatCard label="Total due" value={formatNgn(billing.total_due_ngn)} />
        <StatCard label="Total paid" value={formatNgn(billing.total_paid_ngn)} />
        <StatCard label="Outstanding" value={outstanding > 0 ? formatNgn(outstanding) : '—'} />
      </div>

      {/* Breakdown */}
      <SectionHead
        title="Invoice breakdown"
        action={
          <Button variant="secondary" size="sm" loading={invoiceLoading} onClick={() => void handleDownloadInvoice()}>
            Download invoice
          </Button>
        }
      />
      {invoiceError && (
        <div className={styles.bannerGap}>
          <Banner variant="error">{invoiceError}</Banner>
        </div>
      )}
      <Card padding="default">
        <Kvp label="CBM" value={<Mono>{Number(billing.total_cbm).toFixed(3)}</Mono>} />
        {/* A per-package-type invoice was actually priced against separate
            carton/bag/bale rates — showing only the blended USD-equivalent
            "Rate" line here would correspond to nothing the customer was
            really charged against, so show the real breakdown instead. */}
        {billing.cbm_rate_mode === 'per_package_type' && billing.cbm_breakdown ? (
          (['carton', 'bag', 'bale'] as const).map((bucket) => {
            const item = billing.cbm_breakdown![bucket]
            if (Number(item.cbm) <= 0) return null
            const sym = billing.cbm_rate_currency === 'NGN' ? '₦' : '$'
            return (
              <Kvp
                key={bucket}
                label={`${bucket.charAt(0).toUpperCase()}${bucket.slice(1)}s`}
                value={<Mono>{Number(item.cbm).toFixed(3)} CBM × {sym}{Number(item.rate).toFixed(2)}</Mono>}
              />
            )
          })
        ) : (
          <Kvp label="Rate" value={<Mono>${Number(billing.cbm_rate_usd).toFixed(2)} / CBM</Mono>} />
        )}
        <Kvp label="Exchange rate" value={<Mono>{formatNgn(billing.dollar_rate)} / $</Mono>} />
        <Kvp label="Shipping cost (CBM subtotal)" value={<Mono>{formatNgn(billing.subtotal_ngn)}</Mono>} />
        {/*
          Itemized by real description, never a lump "Misc fees" line — a
          customer looking at money owed should be able to tell exactly what
          each charge is for. Ground-truth gap found live: this card used to
          omit misc fees from the customer's own bill entirely (they were
          silently folded into total_due_ngn with no visible line item at
          all), and other customer surfaces that did show them used the
          ambiguous lump label. See frontend/07_domain_modules.md.
        */}
        {billing.misc_fees.map((fee, i) => (
          <Kvp key={i} label={fee.description} value={<Mono>{formatNgn(fee.amount_ngn)}</Mono>} />
        ))}
        {Number(billing.storage_fees_ngn) > 0 && (
          <Kvp label="Storage fees" value={<Mono>{formatNgn(billing.storage_fees_ngn)}</Mono>} />
        )}
        {Number(billing.carryover_ngn) > 0 && (
          <Kvp
            label="Carryover applied from a previous shipment"
            value={<Mono>+{formatNgn(billing.carryover_ngn)}</Mono>}
          />
        )}
        {Number(billing.adjustments_ngn) !== 0 && (
          <Kvp
            label="CBM dispute adjustment"
            value={
              <Mono color="var(--color-success)">
                −{formatNgn(Math.abs(Number(billing.adjustments_ngn)))}
              </Mono>
            }
          />
        )}
        <Kvp label="Total due" value={<Mono>{formatNgn(billing.total_due_ngn)}</Mono>} />
        <Kvp
          label="Total paid"
          value={<Mono color="var(--color-success)">−{formatNgn(billing.total_paid_ngn)}</Mono>}
        />
        <Kvp
          label="Outstanding"
          value={
            <Mono color={outstanding > 0 ? 'var(--color-error)' : 'var(--color-success)'}>
              {formatNgn(outstanding)}
            </Mono>
          }
          divider={false}
        />
      </Card>

      {/* Payment options */}
      {needsPayment && (
        <>
          <SectionHead title="Pay now" sub={`${formatNgn(outstanding)} outstanding`} />

          {/* A pending bank-transfer claim means money may already be on its
              way — showing "Pay online" / bank-transfer instructions here too
              would openly invite a second, real payment on top of it. Ground-
              truth gap found live: the outstanding amount and "Pay online"
              stayed fully active and clickable even after the customer had
              already told us they'd paid, with nothing on the page saying so. */}
          {pendingClaim ? (
            <Card padding="default">
              <Banner variant="warning" title="Payment submitted — awaiting confirmation">
                You told us you sent {formatNgn(pendingClaim.amount_ngn)} on{' '}
                {formatDate(pendingClaim.submitted_at)}
                {' '}(evidence: {pendingClaim.evidence_file_name}). Staff will confirm it against your evidence
                shortly — the outstanding balance above will update automatically once they do. To avoid a
                duplicate payment, "Pay online" is disabled while this claim is pending.
              </Banner>
            </Card>
          ) : (
            <>
              {latestClaim?.status === 'rejected' && (
                <div className={styles.sectionGap}>
                  <Banner variant="error" title="Your last payment claim was rejected">
                    {latestClaim.rejection_reason ?? 'Contact your shipping company for details.'} You can pay
                    online or submit a new bank-transfer claim below.
                  </Banner>
                </div>
              )}
              <div className={styles.paymentOptions}>
                {/* Pay online — Paystack hosted checkout (B12) */}
                <div className={styles.paymentOption}>
                  <p className={styles.paymentOptionTitle}>Pay online</p>
                  <p className={styles.paymentOptionDesc}>
                    Instant card, transfer, or USSD payment via Paystack. You'll be redirected to a
                    secure checkout page.
                  </p>
                  {payError && (
                    <div className={styles.noteGap}>
                      <Banner variant="error">{payError}</Banner>
                    </div>
                  )}
                  <Button variant="accent" loading={payLoading} onClick={() => void handlePayOnline()}>
                    Pay {formatNgn(outstanding)} online
                  </Button>
                  <p className={styles.fieldHint}>
                    Payments are confirmed automatically — your release note is issued once settled.
                  </p>
                </div>

                {/* Manual bank transfer */}
                <div className={styles.paymentOption}>
                  <p className={styles.paymentOptionTitle}>Manual bank transfer</p>
                  <p className={styles.paymentOptionDesc}>
                    Transfer to our account and staff will confirm your payment.
                  </p>
                  {showTransfer ? (
                    <>
                      <BankTransferDetails config={bankConfig} />
                      <div className={styles.topGap12}>
                        <PaymentClaimPanel
                          billingId={billing.id}
                          outstandingNgn={outstanding}
                          onSubmitted={(claim) =>
                            qc.setQueryData<PaymentClaim[]>(claimsKey, (prev) => [claim, ...(prev ?? [])])
                          }
                        />
                      </div>
                    </>
                  ) : (
                    <Button variant="secondary" onClick={() => setTransferOpened(true)}>
                      Show bank details
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </>
      )}

      {isPaid && billing.outstanding_ngn !== '0' && Number(billing.outstanding_ngn) < 0 && (
        <div className={`${styles.banner} ${styles.topGap16}`}>
          <Banner variant="info" title="Overpayment">
            You have overpaid by {formatNgn(Math.abs(outstanding))}. A refund or credit will be arranged by our team.
          </Banner>
        </div>
      )}

      {/* Payment history */}
      {billing.payments.length > 0 && (
        <>
          <SectionHead title="Payment history" />
          <Card padding="none">
            <table className={styles.paymentsTable}>
              <thead>
                <tr className={styles.paymentsHeadRow}>
                  {['Amount', 'Method', 'Reference', 'Date'].map((h) => (
                    <th key={h} className={styles.paymentsTh}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {billing.payments.map((p, i) => (
                  <tr key={p.id} style={{ borderBottom: i < billing.payments.length - 1 ? '1px solid var(--color-line-soft)' : 'none' }}>
                    <td className={styles.paymentsTd}><Mono>{formatNgn(p.amount_ngn)}</Mono></td>
                    <td className={styles.paymentsTd}>{p.payment_method ?? '—'}</td>
                    <td className={styles.paymentsTd}><Mono>{p.payment_reference ?? '—'}</Mono></td>
                    <td className={styles.paymentsTd}>{formatDate(p.confirmed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {showDispute && (
        <CbmDisputeModal
          billing={billing}
          onCancel={() => setShowDispute(false)}
          onSuccess={() => {
            setShowDispute(false)
            setDisputeFiled(true)
          }}
        />
      )}
    </div>
  )
}
