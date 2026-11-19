import { useRef, useState, type JSX } from 'react'
import { ApiError } from '../../../api/client'
import { billingApi, type Billing, type RecordPaymentInput } from '../../../api/billing'
import {
  Action,
  Badge,
  Banner,
  Button,
  Field,
  Icon,
  Mono,
  DialogGuard,
} from '../../../design/components'
import styles from '../BillingDetail.module.css'
import { formatNgn } from '../../../lib/format'
import { STATUS_VARIANT, statusLabel } from './status'

// ---------------------------------------------------------------------------
// RecordPaymentModal
// ---------------------------------------------------------------------------

export interface RecordPaymentModalProps {
  billing: Billing
  onCancel: () => void
  onSuccess: (updated: { new_payment_status: string }) => void
}

const PAYMENT_METHODS = ['bank_transfer', 'cash', 'online', 'card', 'other']

export function RecordPaymentModal({
  billing,
  onCancel,
  onSuccess,
}: RecordPaymentModalProps): JSX.Element {
  const idempotencyKey = useRef(crypto.randomUUID())
  const outstanding = Number(billing.outstanding_ngn)
  // Pre-fill with the outstanding balance — the common case is recording the
  // full amount due; staff can edit down for a partial payment.
  const [amount, setAmount] = useState(outstanding > 0 ? String(outstanding) : '')
  const [method, setMethod] = useState('')
  const [reference, setReference] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const enteredAmount = Number(amount)
  const isOverpayment = enteredAmount > 0 && enteredAmount > outstanding
  const ngn = formatNgn

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: RecordPaymentInput = { amount_ngn: amount }
      if (method) body.payment_method = method
      if (reference) body.payment_reference = reference
      const result = await billingApi.recordPayment(billing.id, body, idempotencyKey.current)
      onSuccess(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not record payment.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = enteredAmount > 0 && !isNaN(enteredAmount) && !submitting

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Record payment</h3>
        <p className={styles.modalSub}>
          Confirm the amount received and who it’s from before recording.
        </p>

        {/* Context: who is paying + for what, so staff verify before recording */}
        <div className={styles.payCtx}>
          <div className={styles.payCtxCustomer}>
            <Icon name="user" size={16} color="var(--color-ink-3)" />
            <span className={styles.payCtxName}>{billing.customer_name ?? 'Unknown customer'}</span>
          </div>
          {(billing.customer_phone || billing.customer_email) && (
            <div className={styles.payCtxContacts}>
              {billing.customer_phone && (
                <span className={styles.payCtxContact}>
                  <Icon name="phone" size={12} color="var(--color-ink-4)" />
                  {billing.customer_phone}
                </span>
              )}
              {billing.customer_email && (
                <span className={styles.payCtxContact}>
                  <Icon name="mail" size={12} color="var(--color-ink-4)" />
                  {billing.customer_email}
                </span>
              )}
            </div>
          )}
          <div className={styles.payCtxMeta}>
            <span>
              Invoice <Mono>{billing.invoice_number ?? '—'}</Mono>
            </span>
            <span>
              Container <Mono>{billing.container_number ?? '—'}</Mono>
            </span>
            <span>
              Status{' '}
              <Badge variant={STATUS_VARIANT[billing.payment_status]}>
                {statusLabel(billing.payment_status)}
              </Badge>
            </span>
          </div>
          <div className={styles.paySummary}>
            <div className={styles.paySummaryItem}>
              <span className={styles.paySummaryLabel}>Total due</span>
              <span className={styles.paySummaryValue}>{ngn(billing.total_due_ngn)}</span>
            </div>
            <div className={styles.paySummaryItem}>
              <span className={styles.paySummaryLabel}>Already paid</span>
              <span className={styles.paySummaryValue}>{ngn(billing.total_paid_ngn)}</span>
            </div>
            <div className={styles.paySummaryItem}>
              <span className={styles.paySummaryLabel}>Outstanding</span>
              <span
                className={[styles.paySummaryValue, styles.paySummaryValueOutstanding].join(' ')}
              >
                {ngn(billing.outstanding_ngn)}
              </span>
            </div>
          </div>
        </div>

        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">
              {error}
            </Banner>
          </div>
        )}
        {isOverpayment && (
          <div className={styles.modalBanner}>
            <Banner variant="warning">
              Amount entered exceeds outstanding balance of {formatNgn(outstanding)} — overpayment
              will accrue as a carryover credit.
            </Banner>
          </div>
        )}
        <Field
          label="Amount (₦)"
          name="amount_ngn"
          required
          type="number"
          placeholder="e.g. 50000"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <div className={styles.selectField}>
          <label className={styles.selectLabel}>
            Payment method <span className={styles.optional}>Optional</span>
          </label>
          <select
            className={styles.select}
            value={method}
            onChange={(e) => setMethod(e.target.value)}
          >
            <option value="">Select method…</option>
            {PAYMENT_METHODS.map((m) => (
              <option key={m} value={m}>
                {m.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>
        <Field
          label="Reference"
          name="payment_reference"
          placeholder="Bank reference or receipt number"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Action
            variant="primary"
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            Confirm payment
          </Action>
        </div>
      </div>
    </div>
  )
}
