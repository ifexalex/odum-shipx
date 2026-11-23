import { useMemo, useState, type JSX } from 'react'
import { ApiError } from '../../../api/client'
import { billingApi, type Billing, type Carryover } from '../../../api/billing'
import { useChargeTypes } from '../../../hooks/useConfig'
import { Banner, Button, Field, DialogGuard, LinesSkeleton, Select } from '../../../design/components'
import styles from '../BillingDetail.module.css'
import { formatNgn } from '../../../lib/format'
import { toast } from '../../../design/toast'

// ---------------------------------------------------------------------------
// CancelBillingModal
// ---------------------------------------------------------------------------

export interface CancelBillingModalProps {
  onCancel: () => void
  onSuccess: (updated: Billing) => void
  billingId: string
  error: string | null
  /** Customer credit this invoice used (`-adjustments_ngn`): cancelling gives it back. */
  creditsNgn?: string | number
  /** Earlier balances this invoice carried over: cancelling makes them outstanding again for the next invoice. */
  carryoverNgn?: string | number
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
      toast.success('Charge added', billing.invoice_number ?? undefined)
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
          <Select label="Charge type"
            value={selectedType}
            onChange={(e) => handleTypeChange(e.target.value)}
          >
            <option value="other">Other (free-form)</option>
            {chargeTypes.map((t) => (
              <option key={t.id} value={t.name}>
                {t.name} — default {formatNgn(t.amount_ngn)}
              </option>
            ))}
          </Select>
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
  creditsNgn = 0,
  carryoverNgn = 0,
}: CancelBillingModalProps): JSX.Element {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setLocalError(null)
    try {
      const updated = await billingApi.cancel(billingId, { cancel_reason: reason })
      toast.success('Invoice cancelled')
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
        {(Number(creditsNgn) > 0 || Number(carryoverNgn) > 0) && (
          <div className={styles.modalBanner}>
            <Banner variant="info" title="What cancelling gives back">
              {Number(creditsNgn) > 0 && <>{formatNgn(creditsNgn)} of credit goes back to the customer. </>}
              {Number(carryoverNgn) > 0 && (
                <>{formatNgn(carryoverNgn)} carried over from earlier invoices is owed again, on their next invoice.</>
              )}
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
  loading?: boolean
  onCancel: () => void
  onSuccess: () => void
}

export function ApplyCarryoverModal({
  billing,
  carryovers,
  loading = false,
  onCancel,
  onSuccess,
}: ApplyCarryoverModalProps): JSX.Element {
  const [selectedId, setSelectedId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const outstanding = carryovers.filter((c) => c.status === 'outstanding')
  const selected = outstanding.find((c) => c.id === selectedId) ?? null
  const currentTotal = Number(billing.total_due_ngn ?? 0)
  const newTotal = selected ? currentTotal + Number(selected.amount_ngn) : currentTotal

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      await billingApi.applyCarryover(billing.id, selectedId)
      toast.success('Carryover balance applied', billing.invoice_number ?? undefined)
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
        <h3 className={styles.modalTitle}>Apply carryover balance</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">
              {error}
            </Banner>
          </div>
        )}
        {loading ? (
          <LinesSkeleton label="Loading outstanding carryover balances" />
        ) : outstanding.length === 0 ? (
          <p className={styles.emptyNote}>No outstanding carryover balances for this customer.</p>
        ) : (
          <>
            <div className={styles.selectField}>
              <Select label="Unpaid carryover balance to add"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                <option value="">Select a carryover…</option>
                {outstanding.map((c) => (
                  <option key={c.id} value={c.id}>
                    +{formatNgn(c.amount_ngn)} — from{' '}
                    {c.source_container_number ?? 'An earlier invoice'}
                  </option>
                ))}
              </Select>
            </div>
            {selected && (
              <Banner variant="info" title="Updated invoice total">
                Adding {formatNgn(selected.amount_ngn)} brings total due from {formatNgn(currentTotal)} to{' '}
                <strong>{formatNgn(newTotal)}</strong>.
              </Banner>
            )}
          </>
        )}
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={submitting}
            disabled={loading || !selectedId || outstanding.length === 0 || submitting}
            onClick={() => void handleSubmit()}
          >
            Apply balance
          </Button>
        </div>
      </div>
    </div>
  )
}
