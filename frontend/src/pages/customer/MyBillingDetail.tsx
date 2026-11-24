import { useRef, useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { billingApi, disputeApi, paymentClaimApi, type Billing, type PaymentClaim } from '../../api/billing'
import { billingKeys } from '../../api/keys'
import { type BankTransferConfig } from '../../api/tenantManagement'
import { useBankTransferConfig } from '../../hooks/useConfig'
import { STALE_30S } from '../../lib/queryClient'
import { Field, Modal, StatusBadge, PageSkeleton } from '../../design/components'
import { Badge, Banner, Button, Kvp, Mono } from '../../design/components'
import { EvidenceUploader, type UploadedEvidence } from '../nigeria/EvidenceUploader'
import { PaymentsTable } from '../nigeria/billingDetail/Breakdown'
import { InvoiceBreakdown } from '../shared/InvoiceBreakdown'
import { DetailPage } from '../../shell/DetailPage'
import { Section } from '../../shell/Section'
import { ReleaseNoteCard } from './ReleaseNoteCard'
import styles from './customer.module.css'
import { formatCbm, formatDate, formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { PageHeader } from '../../shell/PageHeader'
import { toast } from '../../design/toast'
import { runDocument } from '../../lib/documents'

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
      toast.success('Payment submitted', 'Staff will confirm it shortly.')
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
      toast.success('CBM dispute filed', 'We will look into it and reply on this invoice.')
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not file the dispute.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onCancel} title="Dispute the CBM measurement" size="sm">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error" title="Could not file dispute">{error}</Banner>}
        <Banner variant="info" title={`We measured ${formatCbm(billing.total_cbm)} CBM`}>
          If your own measurement differs, file a dispute — our team acknowledges within 24 hours and
          re-measures. Your invoice is adjusted automatically if the correction is upheld.
        </Banner>
        <Field
          label="Your measured CBM"
          name="disputed_cbm"
          required
          type="number"
          placeholder={`e.g. ${formatCbm(Math.max(0, Number(billing.total_cbm) - 0.07))}`}
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
    </Modal>
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

  // The branded invoice PDF (FD-39), not the data export; feedback while it is prepared and if it fails (FD-44).
  async function handleDownloadInvoice(): Promise<void> {
    if (!billing) return
    setInvoiceLoading(true)
    try {
      await runDocument('your invoice', () => billingApi.invoicePdf(billing.id))
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

  if (isLoading && !billing) return <PageSkeleton kind="detail" label="Loading the page" />
  if (error && !billing) return (
    <div className={styles.page}>
      <PageHeader title="Invoice" />
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
    <>
      <DetailPage
        header={
          <PageHeader
            title={billing.invoice_number ? `Invoice ${billing.invoice_number}` : 'Invoice'}
            status={
              <StatusBadge kind="invoice" status={billing.payment_status} audience="customer" />
            }
            meta={[
              billing.container_number && (
                <>
                  Container <Mono>{billing.container_number}</Mono>
                </>
              ),
              billing.billed_at && `Billed ${formatDate(billing.billed_at)}`,
            ]}
            // The next step is paying (FD-22): it leads, and on a phone it is the bar at the bottom of the screen. Not
            // while a bank-transfer claim is pending, which would invite a second payment.
            primary={
              needsPayment &&
              !pendingClaim && (
                <Button variant="accent" loading={payLoading} onClick={() => void handlePayOnline()}>
                  Pay {formatNgn(outstanding)}
                </Button>
              )
            }
            // A refund is for money already paid: offered only then, and out of the way.
            more={
              Number(billing.total_paid_ngn) > 0 && billing.payment_status !== 'cancelled'
                ? [
                    {
                      label: 'Request a refund',
                      icon: 'refresh',
                      onSelect: () => navigate(`/my-billing/${billing.id}/refund-request`),
                    },
                  ]
                : []
            }
            moreLabel="More invoice actions"
            actions={
              billing._active_disputes.length === 0 &&
              !disputeFiled &&
              billing.payment_status !== 'cancelled' && (
                <Button variant="secondary" onClick={() => setShowDispute(true)}>
                  Dispute CBM
                </Button>
              )
            }
          />
        }
        notices={
          <>
            {payError && (
              <Banner variant="error" title="Couldn't start the payment">
                {payError}
              </Banner>
            )}
            {(disputeFiled || billing._active_disputes.length > 0) && (
              <Banner variant="info" title="CBM dispute open">
                Your dispute is with our team — we acknowledge within 24 hours and re-measure.
                You&apos;ll be notified of the outcome.
              </Banner>
            )}
            {isPaid && billing.outstanding_ngn !== '0' && Number(billing.outstanding_ngn) < 0 && (
              <Banner variant="info" title="Overpayment">
                You have overpaid by {formatNgn(Math.abs(outstanding))}. A refund or credit will be
                arranged by our team.
              </Banner>
            )}
          </>
        }
        // The totals, once (FD-19): they were three stat cards above a breakdown that repeated them.
        aside={
          <Section title="Summary">
            <Kvp label="Total due" value={<Mono>{formatNgn(billing.total_due_ngn)}</Mono>} />
            <Kvp label="Paid" value={<Mono>{formatNgn(billing.total_paid_ngn)}</Mono>} />
            <Kvp
              label="Outstanding"
              value={
                <Mono color={outstanding > 0 ? 'var(--color-error)' : 'var(--color-success)'}>
                  {formatNgn(outstanding)}
                </Mono>
              }
            />
          </Section>
        }
      >
        <ReleaseNoteCard containerId={billing.container_id} />
        <Section
          title="Invoice breakdown"
          action={
            <Button
              variant="secondary"
              size="sm"
              loading={invoiceLoading}
              onClick={() => void handleDownloadInvoice()}
            >
              Download invoice
            </Button>
          }
        >
          {/* The same breakdown staff read (FD-19). */}
          <InvoiceBreakdown billing={billing} />
        </Section>
        {needsPayment && (
          <Section title="Pay now" sub={`${formatNgn(outstanding)} outstanding`}>
            {/* A pending bank-transfer claim means money may already be on its
                way — showing "Pay online" / bank-transfer instructions here too
                would openly invite a second, real payment on top of it. Ground-
                truth gap found live: the outstanding amount and "Pay online"
                stayed fully active and clickable even after the customer had
                already told us they'd paid, with nothing on the page saying so. */}
            {pendingClaim ? (
              <Banner variant="warning" title="Payment submitted — awaiting confirmation">
                You told us you sent {formatNgn(pendingClaim.amount_ngn)} on{' '}
                {formatDate(pendingClaim.submitted_at)} (evidence: {pendingClaim.evidence_file_name}
                ). Staff will confirm it against your evidence shortly — the outstanding balance
                above will update automatically once they do. To avoid a duplicate payment, "Pay
                online" is disabled while this claim is pending.
              </Banner>
            ) : (
              <>
                {latestClaim?.status === 'rejected' && (
                  <div className={styles.sectionGap}>
                    <Banner variant="error" title="Your last payment claim was rejected">
                      {latestClaim.rejection_reason ?? 'Contact your shipping company for details.'}{' '}
                      You can pay online or submit a new bank-transfer claim below.
                    </Banner>
                  </div>
                )}
                <div className={styles.paymentOptions}>
                  {/* Pay online — Paystack hosted checkout (B12) */}
                  <div className={styles.paymentOption}>
                    <p className={styles.paymentOptionTitle}>Pay online</p>
                    <p className={styles.paymentOptionDesc}>
                      Instant card, transfer, or USSD payment via Paystack. You'll be redirected to
                      a secure checkout page.
                    </p>
                    <Button
                      variant="accent"
                      loading={payLoading}
                      onClick={() => void handlePayOnline()}
                    >
                      Pay {formatNgn(outstanding)} online
                    </Button>
                    <p className={styles.fieldHint}>
                      {billing.released_with_outstanding
                        ? 'Payments are confirmed automatically and your balance updates right away.'
                        : 'Payments are confirmed automatically — your release note is issued once settled.'}
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
                              qc.setQueryData<PaymentClaim[]>(claimsKey, (prev) => [
                                claim,
                                ...(prev ?? []),
                              ])
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
          </Section>
        )}
        {/* Payment history: the same table staff see (FD-13). */}
        <PaymentsTable payments={billing.payments} title="Payment history" />
      </DetailPage>
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
    </>
  )
}
