import { useMemo, useState, type JSX } from 'react'
import { ApiError } from '../../../api/client'
import { billingApi, type Billing, type Carryover } from '../../../api/billing'
import { useChargeTypes } from '../../../hooks/useConfig'
import { Banner, Button, Field, DialogGuard } from '../../../design/components'
import styles from '../BillingDetail.module.css'
import { formatNgn } from '../../../lib/format'

// ---------------------------------------------------------------------------
// CancelBillingModal
// ---------------------------------------------------------------------------

export interface CancelBillingModalProps {
  onCancel: () => void
  onSuccess: (updated: Billing) => void
  billingId: string
  error: string | null
}

// ---------------------------------------------------------------------------
// AddChargeModal — prototype 7.2 (billing-screens.jsx AddChargeModal):
// charge-type select seeded from tenant charge types (with default amounts),
// description override, editable amount, and a total-impact banner.
// ---------------------------------------------------------------------------

export interface AddChargeModalProps {
  billing: Billing
  onCancel: () => void
  onSuccess: () => void
}

export function AddChargeModal({ billing, onCancel, onSuccess }: AddChargeModalProps): JSX.Element {
  // Non-fatal: if the types cannot be read, the free-form "other" path still works.
  const { data: allChargeTypes } = useChargeTypes()
  const chargeTypes = useMemo(
    () => (allChargeTypes ?? []).filter((t) => t.is_active),
    [allChargeTypes],
  )
  const [selectedType, setSelectedType] = useState<string>('other')
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleTypeChange(name: string): void {
    setSelectedType(name)
    const t = chargeTypes.find((ct) => ct.name === name)
    if (t) {
      // Pre-fill from the charge-type default; both stay editable.
      setAmount(String(Number(t.amount_ngn)))
      if (!description) setDescription(t.description ?? t.name)
    }
  }

  const amountNum = Number(amount)
  const newTotal = Number(billing.total_due_ngn) + (amountNum > 0 ? amountNum : 0)
  const newOutstanding = Number(billing.outstanding_ngn) + (amountNum > 0 ? amountNum : 0)
  const canSubmit = description.trim().length > 0 && amountNum > 0 && !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const configured =
        selectedType === 'other' ? undefined : chargeTypes.find((ct) => ct.name === selectedType)
      await billingApi.addMiscCharge(billing.id, {
        description,
        amount_ngn: amount,
        charge_type: configured ? 'service_charge' : 'other',
        charge_type_id: configured?.id,
      })
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not add charge.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Add miscellaneous charge</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">
              {error}
            </Banner>
          </div>
        )}

        <div>
          <label
            style={{
              fontWeight: 600,
              fontSize: '0.875rem',
              display: 'block',
              marginBottom: 6,
            }}
          >
            Charge type <span style={{ color: 'var(--color-error)' }}>*</span>
          </label>
          <select
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid var(--color-line)',
              background: 'var(--color-surface)',
              fontSize: '0.875rem',
            }}
            value={selectedType}
            onChange={(e) => handleTypeChange(e.target.value)}
          >
            <option value="other">Other (free-form)</option>
            {chargeTypes.map((t) => (
              <option key={t.id} value={t.name}>
                {t.name} — default {formatNgn(t.amount_ngn)}
              </option>
            ))}
          </select>
        </div>

        <Field
          label="Description"
          name="charge_description"
          required
          placeholder="e.g. Customs examination at Tin Can Port"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <Field
          label="Amount (₦)"
          name="charge_amount"
          required
          type="number"
          placeholder="e.g. 15000"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />

        {amountNum > 0 && (
          <Banner
            variant="info"
            title={`This charge will be added to ${billing.invoice_number ?? 'this billing'}`}
          >
            Total due increases to {formatNgn(newTotal)}. Outstanding increases to{' '}
            {formatNgn(newOutstanding)}.
          </Banner>
        )}

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon="plus"
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            Add charge
          </Button>
        </div>
      </div>
    </div>
  )
}

export function CancelBillingModal({
  onCancel,
  onSuccess,
  billingId,
  error,
}: CancelBillingModalProps): JSX.Element {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setLocalError(null)
    try {
      const updated = await billingApi.cancel(billingId, { cancel_reason: reason })
      onSuccess(updated)
    } catch (err) {
      setLocalError(err instanceof ApiError ? err.message : 'Could not cancel billing.')
    } finally {
      setSubmitting(false)
    }
  }

  const displayError = localError ?? error

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Cancel billing record</h3>
        {displayError && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">
              {displayError}
            </Banner>
          </div>
        )}
        <Field
          label="Cancel reason"
          name="cancel_reason"
          required
          multiline
          placeholder="Why is this billing record being voided?"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="danger"
            loading={submitting}
            disabled={!reason.trim() || submitting}
            onClick={() => void handleSubmit()}
          >
            Void billing
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ApplyCarryoverModal
// ---------------------------------------------------------------------------

export interface ApplyCarryoverModalProps {
  billing: Billing
  carryovers: Carryover[]
  onCancel: () => void
  onSuccess: () => void
}

export function ApplyCarryoverModal({
  billing,
  carryovers,
  onCancel,
  onSuccess,
}: ApplyCarryoverModalProps): JSX.Element {
  const [selectedId, setSelectedId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const outstanding = carryovers.filter((c) => c.status === 'outstanding')

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      await billingApi.applyCarryover(billing.id, selectedId)
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not apply carryover.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Apply carryover credit</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">
              {error}
            </Banner>
          </div>
        )}
        {outstanding.length === 0 ? (
          <p className={styles.emptyNote}>No outstanding carryover credits for this customer.</p>
        ) : (
          <div className={styles.selectField}>
            <label className={styles.selectLabel}>
              Carryover to apply <span className={styles.required}>*</span>
            </label>
            <select
              className={styles.select}
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              <option value="">Select a carryover…</option>
              {outstanding.map((c) => (
                <option key={c.id} value={c.id}>
                  {formatNgn(c.amount_ngn)} — from{' '}
                  {c.source_container_number ?? c.source_billing_id}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={submitting}
            disabled={!selectedId || outstanding.length === 0 || submitting}
            onClick={() => void handleSubmit()}
          >
            Apply credit
          </Button>
        </div>
      </div>
    </div>
  )
}
