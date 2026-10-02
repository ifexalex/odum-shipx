import { useCallback, useEffect, useRef, useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  billingApi,
  carryoverApi,
  disputeApi,
  paymentClaimApi,
  type Billing,
  type Carryover,
  type CBMDispute,
  type RecordPaymentInput,
  type ResolveCBMDisputeInput,
  type StorageFeeEntry,
} from '../../api/billing'
import {
  canAcknowledgeDispute,
  canApplyCarryover,
  canCancelBilling,
  canRecordPayment,
  canRejectDispute,
  canResolveDispute,
  isTerminalDisputeStatus,
} from '../../api/billingRules'
import { releaseNotesApi } from '../../api/releaseNotes'
import { useSession } from '../../auth/useSession'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { billingKeys, releaseNoteKeys } from '../../api/keys'
import { configApi, type ChargeType } from '../../api/tenantManagement'
import { useWarehouses } from '../../hooks/useWarehouses'
import { Action, Badge, Banner, Button, Card, ExportButton, Field, Icon, Mono, StatCard, Table, type BadgeVariant } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './BillingDetail.module.css'

// ---------------------------------------------------------------------------
// Status helpers (shared across this file)
// ---------------------------------------------------------------------------

type PaymentStatus = Billing['payment_status']

const STATUS_VARIANT: Record<PaymentStatus, BadgeVariant> = {
  unpaid: 'error',
  partially_paid: 'warning',
  paid: 'success',
  overpaid: 'warning',
  waived: 'neutral',
  released_with_outstanding: 'warning',
  cancelled: 'neutral',
}

function statusLabel(status: PaymentStatus): string {
  switch (status) {
    case 'unpaid': return 'Unpaid'
    case 'partially_paid': return 'Partially paid'
    case 'paid': return 'Paid'
    case 'overpaid': return 'Overpaid'
    case 'waived': return 'Waived'
    case 'released_with_outstanding': return 'Released (outstanding)'
    case 'cancelled': return 'Cancelled'
  }
}

function disputeStatusLabel(status: CBMDispute['status']): string {
  switch (status) {
    case 'submitted': return 'Submitted'
    case 'acknowledged': return 'Acknowledged'
    case 'investigating': return 'Investigating'
    case 'escalated_china': return 'Escalated to China'
    case 'resolved_adjusted': return 'Resolved — adjusted'
    case 'resolved_no_change': return 'Resolved — no change'
    case 'closed': return 'Closed'
  }
}

function disputeVariant(status: CBMDispute['status']): BadgeVariant {
  if (status === 'resolved_adjusted' || status === 'resolved_no_change' || status === 'closed') return 'success'
  if (status === 'escalated_china') return 'error'
  return 'warning'
}

// ---------------------------------------------------------------------------
// StorageFeeBanner — 3 states matching gapfix-screens-b.jsx B3
// ---------------------------------------------------------------------------

const GRACE_PERIOD_DAYS = 14
const ENDING_SOON_THRESHOLD = 3 // days left before "ending soon" state kicks in

function fmtDate(d: Date): string {
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

interface StorageFeeBannerProps {
  billing: { storage_fees_ngn: string | number; release_note_issued_at?: string | null }
  storageFees: StorageFeeEntry[]
  canWaive: boolean
  onWaive: () => void
  waiving: boolean
}

function StorageFeeBanner({ billing, storageFees, canWaive, onWaive, waiving }: StorageFeeBannerProps): JSX.Element | null {
  const storageFeesNgn = Number(billing.storage_fees_ngn)
  const releaseNoteIssuedAt = billing.release_note_issued_at

  // No release note yet — no grace period to track
  if (!releaseNoteIssuedAt && storageFeesNgn <= 0) return null

  const now = new Date()
  const issued = releaseNoteIssuedAt ? new Date(releaseNoteIssuedAt) : null
  const graceEnds = issued ? new Date(issued.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000) : null
  const daysLeft = graceEnds ? Math.ceil((graceEnds.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)) : null
  const daysPastGrace = daysLeft !== null && daysLeft < 0 ? Math.abs(daysLeft) : 0

  // Derive per-carton daily rate from first fee row (most accurate source)
  const dailyRatePerCarton = storageFees[0] ? Number(storageFees[0].daily_rate_ngn) : 500
  const cartonCount = storageFees[0] ? storageFees[0].carton_count : null
  const totalAccrued = storageFees.reduce((s, r) => s + Number(r.fee_amount_ngn), 0)

  const waiveBtn = canWaive ? (
    <Action variant="danger-outline" size="sm" loading={waiving} onClick={onWaive}>
      Waive fees
    </Action>
  ) : undefined

  // ① Grace — accruing but no fees yet logged (within grace period)
  if (daysLeft !== null && daysLeft > ENDING_SOON_THRESHOLD && storageFeesNgn <= 0) {
    return (
      <Banner variant="info" icon="clock" title={`Free storage until ${fmtDate(graceEnds!)}`}>
        Pickup is free for <strong>{daysLeft} more days</strong>. After the grace period,
        storage accrues at ₦{dailyRatePerCarton.toLocaleString()}/day per carton
        {cartonCount ? ` (${cartonCount} cartons)` : ''}.
      </Banner>
    )
  }

  // ② Grace — ending soon (≤3 days left)
  if (daysLeft !== null && daysLeft > 0 && daysLeft <= ENDING_SOON_THRESHOLD) {
    const dailyTotal = cartonCount ? dailyRatePerCarton * cartonCount : dailyRatePerCarton
    return (
      <Banner variant="warning" icon="warn"
        title={daysLeft === 1 ? 'Storage fees begin tomorrow' : `Storage fees begin in ${daysLeft} days`}
        action={waiveBtn}>
        Grace period ends <strong>{fmtDate(graceEnds!)}</strong>. From day {GRACE_PERIOD_DAYS + 1},
        ₦{dailyTotal.toLocaleString()}/day will accrue
        {cartonCount ? ` (${cartonCount} cartons × ₦${dailyRatePerCarton.toLocaleString()})` : ''}.
        A reminder was sent to the customer today.
      </Banner>
    )
  }

  // ③ Accruing (past grace period, fees accumulating)
  if (storageFeesNgn > 0 || daysPastGrace > 0) {
    const dailyTotal = cartonCount ? dailyRatePerCarton * cartonCount : storageFeesNgn
    return (
      <Banner variant="error" icon="alert" title="Storage fees are accruing" action={waiveBtn}>
        <strong>₦{(totalAccrued || storageFeesNgn).toLocaleString()}</strong> accrued so far
        {daysPastGrace > 0 ? ` (${daysPastGrace} days × ₦${dailyTotal.toLocaleString()})` : ''}.
        This is added to the outstanding balance daily until pickup.
      </Banner>
    )
  }

  return null
}

// ---------------------------------------------------------------------------
// StorageFeeLog — accrual log table
// ---------------------------------------------------------------------------

function StorageFeeLog({ fees }: { fees: StorageFeeEntry[] }): JSX.Element | null {
  if (fees.length === 0) return null
  return (
    <Card padding={0}>
      <Table
        dense
        columns={[
          { title: 'Day' },
          { title: 'Date' },
          { title: 'Cartons', align: 'right' },
          { title: 'Rate', align: 'right' },
          { title: 'Fee', align: 'right' },
        ]}
        rows={fees.map((f) => ({
          cells: [
            <span key="day" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>Day {f.day_number}</span>,
            <Mono key="date" color="var(--color-ink-2)">{new Date(f.accrual_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</Mono>,
            <Mono key="cartons">{f.carton_count}</Mono>,
            <Mono key="rate">₦{Number(f.daily_rate_ngn).toLocaleString()}</Mono>,
            <Mono key="fee" color="var(--color-error)">₦{Number(f.fee_amount_ngn).toLocaleString()}</Mono>,
          ],
        }))}
      />
    </Card>
  )
}

// ---------------------------------------------------------------------------
// DisputeSLA
// ---------------------------------------------------------------------------

function _slaCountdown(deadlineIso: string | null): { label: string; overdue: boolean; urgent: boolean } | null {
  if (!deadlineIso) return null
  const msLeft = new Date(deadlineIso).getTime() - Date.now()
  const overdue = msLeft <= 0
  const urgent = !overdue && msLeft < 24 * 60 * 60 * 1000
  if (overdue) return { label: 'Overdue', overdue: true, urgent: false }
  const hoursLeft = Math.ceil(msLeft / (1000 * 60 * 60))
  const daysLeft = Math.floor(hoursLeft / 24)
  const label = daysLeft > 0 ? `${daysLeft}d ${hoursLeft % 24}h` : `${hoursLeft}h`
  return { label, overdue: false, urgent }
}

interface DisputeSLAProps {
  dispute: CBMDispute
}

function DisputeSLA({ dispute }: DisputeSLAProps): JSX.Element | null {
  const {
    status,
    acknowledged_at = null,
    acknowledge_due_by = null,
    investigate_due_by = null,
    resolve_due_by = null,
    auto_escalated_at = null,
  } = dispute

  const stages: { label: string; deadline: string | null; done: boolean; ts?: string | null }[] = [
    {
      label: 'Acknowledge',
      deadline: acknowledged_at ? null : acknowledge_due_by,
      done: !!acknowledged_at,
      ts: acknowledged_at,
    },
    {
      label: 'Investigate',
      deadline: ['investigating', 'escalated_china', 'escalated'].includes(status) ? investigate_due_by : null,
      done: ['escalated_china', 'escalated', 'resolved_adjusted', 'resolved_no_change', 'closed'].includes(status),
      ts: auto_escalated_at,
    },
    {
      label: 'Resolve',
      deadline: ['investigating', 'escalated_china', 'escalated'].includes(status) ? resolve_due_by : null,
      done: ['resolved_adjusted', 'resolved_no_change', 'closed'].includes(status),
    },
  ]

  return (
    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {stages.map((stage) => {
        const cd = stage.done ? null : _slaCountdown(stage.deadline)
        const color = stage.done
          ? 'var(--color-text-muted)'
          : cd?.overdue
            ? 'var(--color-error)'
            : cd?.urgent
              ? 'var(--color-warning)'
              : 'var(--color-text-muted)'

        return (
          <div key={stage.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color }}>
            <span style={{ fontWeight: 600, minWidth: 80 }}>{stage.label}</span>
            {stage.done ? (
              <span>{stage.ts ? `✓ ${new Date(stage.ts).toLocaleDateString()}` : '✓ Done'}</span>
            ) : cd ? (
              <span>{cd.overdue ? '⚠ Overdue' : `${cd.label} remaining`}</span>
            ) : stage.deadline ? (
              <span>Due {new Date(stage.deadline).toLocaleDateString()}</span>
            ) : (
              <span style={{ color: 'var(--color-text-muted)' }}>—</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// RecordPaymentModal
// ---------------------------------------------------------------------------

interface RecordPaymentModalProps {
  billing: Billing
  onCancel: () => void
  onSuccess: (updated: { new_payment_status: string }) => void
}

const PAYMENT_METHODS = ['bank_transfer', 'cash', 'online', 'card', 'other']

function RecordPaymentModal({ billing, onCancel, onSuccess }: RecordPaymentModalProps): JSX.Element {
  const idempotencyKey = useRef(crypto.randomUUID())
  const [amount, setAmount] = useState('')
  const [method, setMethod] = useState('')
  const [reference, setReference] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const outstanding = Number(billing.outstanding_ngn)
  const enteredAmount = Number(amount)
  const isOverpayment = enteredAmount > 0 && enteredAmount > outstanding

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
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Record payment</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">{error}</Banner>
          </div>
        )}
        {isOverpayment && (
          <div className={styles.modalBanner}>
            <Banner variant="warning">
              Amount entered exceeds outstanding balance of ₦{outstanding.toLocaleString()} — overpayment will accrue as a carryover credit.
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
          <label className={styles.selectLabel}>Payment method <span className={styles.optional}>Optional</span></label>
          <select
            className={styles.select}
            value={method}
            onChange={(e) => setMethod(e.target.value)}
          >
            <option value="">Select method…</option>
            {PAYMENT_METHODS.map((m) => (
              <option key={m} value={m}>{m.replace('_', ' ')}</option>
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
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Action variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Confirm payment
          </Action>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// CancelBillingModal
// ---------------------------------------------------------------------------

interface CancelBillingModalProps {
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

interface AddChargeModalProps {
  billing: Billing
  onCancel: () => void
  onSuccess: () => void
}

function AddChargeModal({ billing, onCancel, onSuccess }: AddChargeModalProps): JSX.Element {
  const [chargeTypes, setChargeTypes] = useState<ChargeType[]>([])
  const [selectedType, setSelectedType] = useState<string>('other')
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const types = await configApi.listChargeTypes()
        setChargeTypes(types.filter((t) => t.is_active))
      } catch {
        // non-fatal — the free-form "other" path still works
      }
    })()
  }, [])

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
      const configured = selectedType === 'other' ? undefined : chargeTypes.find((ct) => ct.name === selectedType)
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
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Add miscellaneous charge</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}

        <div>
          <label style={{ fontWeight: 600, fontSize: '0.875rem', display: 'block', marginBottom: 6 }}>
            Charge type <span style={{ color: 'var(--color-error)' }}>*</span>
          </label>
          <select
            style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--color-line)', background: 'var(--color-surface)', fontSize: '0.875rem' }}
            value={selectedType}
            onChange={(e) => handleTypeChange(e.target.value)}
          >
            <option value="other">Other (free-form)</option>
            {chargeTypes.map((t) => (
              <option key={t.id} value={t.name}>
                {t.name} — default ₦{Number(t.amount_ngn).toLocaleString()}
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
          <Banner variant="info" title={`This charge will be added to ${billing.invoice_number ?? 'this billing'}`}>
            Total due increases to ₦{newTotal.toLocaleString()}. Outstanding increases to ₦{newOutstanding.toLocaleString()}.
          </Banner>
        )}

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" icon="plus" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Add charge
          </Button>
        </div>
      </div>
    </div>
  )
}

function CancelBillingModal({ onCancel, onSuccess, billingId, error }: CancelBillingModalProps): JSX.Element {
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
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Cancel billing record</h3>
        {displayError && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">{displayError}</Banner>
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
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
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

interface ApplyCarryoverModalProps {
  billing: Billing
  carryovers: Carryover[]
  onCancel: () => void
  onSuccess: () => void
}

function ApplyCarryoverModal({ billing, carryovers, onCancel, onSuccess }: ApplyCarryoverModalProps): JSX.Element {
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
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Apply carryover credit</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">{error}</Banner>
          </div>
        )}
        {outstanding.length === 0 ? (
          <p className={styles.emptyNote}>No outstanding carryover credits for this customer.</p>
        ) : (
          <div className={styles.selectField}>
            <label className={styles.selectLabel}>Carryover to apply <span className={styles.required}>*</span></label>
            <select
              className={styles.select}
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              <option value="">Select a carryover…</option>
              {outstanding.map((c) => (
                <option key={c.id} value={c.id}>
                  ₦{Number(c.amount_ngn).toLocaleString()} — from {c.source_container_number ?? c.source_billing_id}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
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

// ---------------------------------------------------------------------------
// GenerateReleaseNoteModal
// ---------------------------------------------------------------------------

interface GenerateReleaseNoteModalProps {
  billing: Billing
  onCancel: () => void
  onSuccess: () => void
}

function GenerateReleaseNoteModal({ billing, onCancel, onSuccess }: GenerateReleaseNoteModalProps): JSX.Element {
  const [releaseMode, setReleaseMode] = useState<'tags' | 'count'>('tags')
  const [tagsRaw, setTagsRaw] = useState('')
  const [packagesReleased, setPackagesReleased] = useState('')
  const [packageUnit, setPackageUnit] = useState('cartons')
  const [releaseWithOutstanding, setReleaseWithOutstanding] = useState(false)
  const [approvalNotes, setApprovalNotes] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [physicalDocumentNumber, setPhysicalDocumentNumber] = useState('')
  const [invoiceNumbersRaw, setInvoiceNumbersRaw] = useState('')
  const [creditGrantedByName, setCreditGrantedByName] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: warehouses = [] } = useWarehouses()

  // Parse comma/newline/space separated tags from the textarea
  const cartonTags = tagsRaw
    .split(/[\n,\s]+/)
    .map((t) => t.trim())
    .filter(Boolean)
  const invoiceNumbers = invoiceNumbersRaw
    .split(/[\n,]+/)
    .map((t) => t.trim())
    .filter(Boolean)
  const packagesReleasedCount = Number(packagesReleased)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      await releaseNotesApi.create({
        billing_id: billing.id,
        carton_tags: releaseMode === 'tags' ? cartonTags : [],
        packages_released: releaseMode === 'count' ? packagesReleasedCount : undefined,
        package_unit: releaseMode === 'count' ? packageUnit.trim() : undefined,
        release_with_outstanding: releaseWithOutstanding,
        approval_notes: approvalNotes || undefined,
        warehouse_id: warehouseId || undefined,
        physical_document_number: physicalDocumentNumber.trim() || undefined,
        packing_list_invoice_numbers: invoiceNumbers.length > 0 ? invoiceNumbers : undefined,
        credit_granted_by_name: releaseWithOutstanding ? creditGrantedByName.trim() || undefined : undefined,
        due_date: releaseWithOutstanding ? dueDate || undefined : undefined,
      })
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not generate release note.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = (releaseMode === 'tags'
    ? cartonTags.length > 0
    : packagesReleasedCount > 0 && packageUnit.trim().length > 0) &&
    (!releaseWithOutstanding || approvalNotes.trim().length > 0) && !submitting

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Generate release note</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}

        <div>
          <label style={{ fontWeight: 600, fontSize: '0.875rem', display: 'block', marginBottom: 6 }}>
            Release by
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              variant={releaseMode === 'tags' ? 'primary' : 'ghost'}
              onClick={() => setReleaseMode('tags')}
            >
              Carton tags
            </Button>
            <Button
              variant={releaseMode === 'count' ? 'primary' : 'ghost'}
              onClick={() => setReleaseMode('count')}
            >
              Count
            </Button>
          </div>
        </div>

        {releaseMode === 'tags' ? (
          <>
            <Field
              label="Carton tags to release"
              name="carton_tags"
              required
              multiline
              placeholder={'One tag per line, or comma-separated\ne.g. ACME-001-001, ACME-001-002'}
              value={tagsRaw}
              onChange={(e) => setTagsRaw(e.target.value)}
            />
            {cartonTags.length > 0 && (
              <p style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)', margin: 0 }}>
                {cartonTags.length} tag(s) parsed
              </p>
            )}
          </>
        ) : (
          <>
            <Field
              label="Packages released"
              name="packages_released"
              type="number"
              required
              placeholder="e.g. 5"
              value={packagesReleased}
              onChange={(e) => setPackagesReleased(e.target.value)}
            />
            <Field
              label="Package unit"
              name="package_unit"
              required
              placeholder="e.g. cartons, bags"
              value={packageUnit}
              onChange={(e) => setPackageUnit(e.target.value)}
            />
          </>
        )}

        {warehouses.length > 0 && (
          <div className={styles.selectField}>
            <label className={styles.selectLabel}>
              Warehouse / branch <span className={styles.optional}>Optional</span>
            </label>
            <select aria-label="Warehouse / branch" className={styles.select} value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
              <option value="">Use tenant default…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                  {w.is_default ? ' (default)' : ''}
                </option>
              ))}
            </select>
          </div>
        )}

        <Field
          label="Physical document number"
          name="physical_document_number"
          optional
          placeholder="Pre-printed serial off a physical release-note booklet, if used"
          value={physicalDocumentNumber}
          onChange={(e) => setPhysicalDocumentNumber(e.target.value)}
        />

        <Field
          label="Packing list invoice numbers"
          name="packing_list_invoice_numbers"
          optional
          placeholder="Comma-separated, e.g. #53534, #53535"
          value={invoiceNumbersRaw}
          onChange={(e) => setInvoiceNumbersRaw(e.target.value)}
        />

        <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', fontSize: '0.875rem' }}>
          <input type="checkbox" checked={releaseWithOutstanding} onChange={(e) => setReleaseWithOutstanding(e.target.checked)} />
          <span>Release with outstanding balance (waive payment requirement)</span>
        </label>

        {releaseWithOutstanding && (
          <>
            <Field
              label="Approval notes"
              name="approval_notes"
              required
              multiline
              placeholder="Manager authorisation reference or reason…"
              value={approvalNotes}
              onChange={(e) => setApprovalNotes(e.target.value)}
            />
            <Field
              label="Credit granted by"
              name="credit_granted_by_name"
              optional
              placeholder="Name of the staff member authorising this credit release"
              value={creditGrantedByName}
              onChange={(e) => setCreditGrantedByName(e.target.value)}
            />
            <Field
              label="Debt payment date"
              name="due_date"
              type="date"
              optional
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
            />
          </>
        )}

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Action variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Generate
          </Action>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ResolveDisputeModal
// ---------------------------------------------------------------------------

interface ResolveDisputeModalProps {
  dispute: CBMDispute
  onCancel: () => void
  onSuccess: (updated: CBMDispute) => void
}

function ResolveDisputeModal({ dispute, onCancel, onSuccess }: ResolveDisputeModalProps): JSX.Element {
  const [outcome, setOutcome] = useState<'resolved_adjusted' | 'resolved_no_change'>('resolved_no_change')
  const [correctedCbm, setCorrectedCbm] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: ResolveCBMDisputeInput = { status: outcome, resolution_notes: notes }
      if (outcome === 'resolved_adjusted' && correctedCbm) body.corrected_cbm = correctedCbm
      const updated = await disputeApi.resolve(dispute.id, body)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve dispute.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit =
    notes.trim().length > 0 &&
    (outcome === 'resolved_no_change' || (outcome === 'resolved_adjusted' && correctedCbm.trim().length > 0))

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Resolve CBM dispute</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">{error}</Banner>
          </div>
        )}
        <div className={styles.outcomeToggle}>
          <Button
            variant={outcome === 'resolved_no_change' ? 'success' : 'secondary'}
            onClick={() => setOutcome('resolved_no_change')}
          >
            No change — CBM stands
          </Button>
          <Button
            variant={outcome === 'resolved_adjusted' ? 'primary' : 'secondary'}
            onClick={() => setOutcome('resolved_adjusted')}
          >
            Adjust CBM
          </Button>
        </div>
        {outcome === 'resolved_adjusted' && (
          <Field
            label="Corrected CBM"
            name="corrected_cbm"
            required
            type="number"
            placeholder={`Original: ${dispute.original_cbm ?? '—'}`}
            value={correctedCbm}
            onChange={(e) => setCorrectedCbm(e.target.value)}
          />
        )}
        <Field
          label="Resolution notes"
          name="resolution_notes"
          required
          multiline
          placeholder="Explain the resolution decision…"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Action variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Resolve dispute
          </Action>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// DisputeCard — inline per active dispute on BillingDetail
// ---------------------------------------------------------------------------

interface DisputeCardProps {
  dispute: CBMDispute
  role: string
  onUpdated: (updated: CBMDispute) => void
}

function DisputeCard({ dispute, role, onUpdated }: DisputeCardProps): JSX.Element {
  const [showResolve, setShowResolve] = useState(false)
  const [acknowledging, setAcknowledging] = useState(false)
  const [rejectingReason, setRejectingReason] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleAcknowledge(): Promise<void> {
    setAcknowledging(true)
    setError(null)
    try {
      const updated = await disputeApi.acknowledge(dispute.id)
      onUpdated(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not acknowledge dispute.')
    } finally {
      setAcknowledging(false)
    }
  }

  async function handleReject(): Promise<void> {
    if (!rejectingReason?.trim()) return
    setRejecting(true)
    setError(null)
    try {
      const updated = await disputeApi.reject(dispute.id, rejectingReason)
      onUpdated(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reject dispute.')
    } finally {
      setRejecting(false)
    }
  }

  const r = role as Parameters<typeof canAcknowledgeDispute>[1]

  return (
    <div className={styles.disputeCard}>
      <div className={styles.disputeHeader}>
        <div className={styles.disputeMeta}>
          <span className={styles.disputeLabel}>CBM dispute</span>
          <Badge variant={disputeVariant(dispute.status)}>{disputeStatusLabel(dispute.status)}</Badge>
          {!isTerminalDisputeStatus(dispute.status) && <DisputeSLA dispute={dispute} />}
        </div>
        <div className={styles.disputeNumbers}>
          {dispute.original_cbm && <span>Original CBM: <Mono>{dispute.original_cbm}</Mono></span>}
          {dispute.corrected_cbm && <span>Corrected: <Mono>{dispute.corrected_cbm}</Mono></span>}
        </div>
      </div>

      {error && (
        <div className={styles.disputeError}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      {!isTerminalDisputeStatus(dispute.status) && (
        <div className={styles.disputeActions}>
          {canAcknowledgeDispute(dispute, r) && (
            <Button variant="secondary" size="sm" loading={acknowledging} onClick={() => void handleAcknowledge()}>
              Acknowledge
            </Button>
          )}
          {canResolveDispute(dispute, r) && (
            <Button variant="primary" size="sm" onClick={() => setShowResolve(true)}>
              Resolve
            </Button>
          )}
          {canRejectDispute(dispute, r) && rejectingReason === null && (
            <Button variant="ghost" size="sm" onClick={() => setRejectingReason('')}>
              Reject
            </Button>
          )}
          {rejectingReason !== null && (
            <div className={styles.inlineReject}>
              <Field
                label="Reject reason"
                name="reject_reason"
                required
                value={rejectingReason}
                onChange={(e) => setRejectingReason(e.target.value)}
                placeholder="Why is this dispute being rejected?"
              />
              <div className={styles.inlineRejectActions}>
                <Button variant="ghost" size="sm" onClick={() => setRejectingReason(null)}>Cancel</Button>
                <Button
                  variant="danger"
                  size="sm"
                  loading={rejecting}
                  disabled={!rejectingReason.trim()}
                  onClick={() => void handleReject()}
                >
                  Confirm reject
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {showResolve && (
        <ResolveDisputeModal
          dispute={dispute}
          onCancel={() => setShowResolve(false)}
          onSuccess={(updated) => {
            setShowResolve(false)
            onUpdated(updated)
          }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function BillingDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'
  const qc = useQueryClient()

  // Ground-truth gap found live, reported by the user: "i approved a
  // payment, but it did not record the payment as paid, until i refreshed
  // the page." Every mutation on this page (record payment, confirm/reject
  // a claim, waive fees, remove a charge, apply a carryover, cancel, a
  // dispute update) only ever refreshed this component's own local
  // `billing`/`carryovers` state (via `load()`/`setBilling()`) — it never
  // invalidated react-query's cache, so `BillingList.tsx`'s own
  // `billingKeys.list(...)` query (5-minute staleTime) kept serving the
  // pre-mutation row on every other screen until a hard refresh discarded
  // the whole QueryClient. Every comparable mutation elsewhere in this
  // codebase (useRecordPayment, useFileDispute, useResolveDispute — see
  // useBilling.ts) already invalidates billingKeys on success; this page's
  // hand-rolled mutations just never did. One shared call, invoked after
  // every local refresh below.
  const invalidateBillingCaches = useCallback(() => {
    void qc.invalidateQueries({ queryKey: billingKeys.all })
  }, [qc])

  // Primary source: billing object passed via router state from BillingList.
  // The backend exposes no GET /v1/billing/{billing-id} endpoint — the
  // GET /v1/billing/{resource-id} route takes a *customer* id, not billing id.
  // Navigation state covers the normal flow; the fallback list fetch covers
  // the case where someone links directly to /billing/:id.
  const stateBilling = (location.state as { billing?: Billing } | null)?.billing ?? null
  const [billing, setBilling] = useState<Billing | null>(stateBilling)
  const [carryovers, setCarryovers] = useState<Carryover[]>([])
  const [loading, setLoading] = useState(stateBilling === null)
  const [error, setError] = useState<string | null>(null)

  const [showPaymentModal, setShowPaymentModal] = useState(false)
  const [showCancelModal, setShowCancelModal] = useState(false)
  const [showCarryoverModal, setShowCarryoverModal] = useState(false)
  const [showReleaseNoteModal, setShowReleaseNoteModal] = useState(false)
  const [showAddChargeModal, setShowAddChargeModal] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [waivingFees, setWaivingFees] = useState(false)
  const [removingChargeId, setRemovingChargeId] = useState<string | null>(null)

  // Storage fee accrual log — loaded lazily once a billing record is known
  const { data: storageFees = [] } = useQuery({
    queryKey: [...billingKeys.detail(id ?? ''), 'storage-fees'],
    queryFn: () => billingApi.listStorageFees(id!),
    enabled: !!id && !!billing && Number(billing.storage_fees_ngn) > 0,
    staleTime: 5 * 60 * 1000,
  })

  // Full misc-charge rows (with ids) — the embedded misc_fees list has no ids,
  // so add/remove (prototype 7.2 AddChargeModal + removable rows) needs this.
  const { data: miscCharges = [], refetch: refetchCharges } = useQuery({
    queryKey: [...billingKeys.detail(id ?? ''), 'charges'],
    queryFn: () => billingApi.listMiscCharges(id!),
    enabled: !!id && !!billing,
    staleTime: 5 * 60 * 1000,
  })

  // Customer-submitted "I've made this payment" claims for this billing —
  // the staff-side half of the manual-bank-transfer confirmation flow.
  const { data: paymentClaims = [], refetch: refetchClaims } = useQuery({
    queryKey: [...billingKeys.detail(id ?? ''), 'payment-claims'],
    queryFn: () => paymentClaimApi.listForBilling(id!),
    enabled: !!id && !!billing,
    staleTime: 30 * 1000,
  })
  const [reviewingClaimId, setReviewingClaimId] = useState<string | null>(null)
  const [rejectingClaimId, setRejectingClaimId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [claimActionError, setClaimActionError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      // Scan the billing list to find by ID — only needed on direct URL access.
      const result = await billingApi.list()
      const found = result.data.find((b) => b.id === id) ?? null
      if (!found) {
        setError('Billing record not found.')
        return
      }
      setBilling(found)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load billing record.')
    } finally {
      setLoading(false)
    }
  }, [id])

  // Only fetch from API if we didn't get the billing from router state
  useEffect(() => {
    if (stateBilling === null) void load()
  }, [load, stateBilling])

  async function loadCarryovers(): Promise<void> {
    if (!billing) return
    try {
      // Billing is per-container (not per-customer), so no customer_id filter —
      // load all outstanding credits and let the staff member pick.
      const result = await carryoverApi.list({ status: 'outstanding' })
      setCarryovers(result.data)
    } catch {
      // non-fatal — user can still see the modal with empty state
    }
  }

  function handleDisputeUpdated(updated: CBMDispute): void {
    if (!billing) return
    setBilling({
      ...billing,
      _active_disputes: billing._active_disputes.map((d) => (d.id === updated.id ? updated : d)),
    })
    invalidateBillingCaches()
  }

  if (loading) return <div className={styles.loadingState}>Loading billing record…</div>
  if (error || !billing) {
    return (
      <div className={styles.loadingState}>
        <Banner variant="error" title="Couldn't load this billing record">{error ?? 'Not found.'}</Banner>
      </div>
    )
  }

  const outstanding = Number(billing.outstanding_ngn)
  const isActionable = canRecordPayment(billing, role)
  const isCarryoverApplicable = canApplyCarryover(billing, role)
  const isCancellable = canCancelBilling(billing, role)
  const canGenerateRelease = (role === 'nigeria_office_staff' || role === 'tenant_admin') &&
    (billing.payment_status === 'paid' || billing.payment_status === 'overpaid' ||
     billing.payment_status === 'partially_paid')
  const canWaiveFees = (role === 'tenant_admin' || role === 'nigeria_office_staff') &&
    Number(billing.storage_fees_ngn) > 0 &&
    !['cancelled', 'waived'].includes(billing.payment_status)
  const isStaff = role === 'tenant_admin' || role === 'nigeria_office_staff'
  // Backend guard: charges can only be removed while the billing is unpaid,
  // and only by tenant_admin (services/billing/handler.py DELETE route).
  const canRemoveCharge = role === 'tenant_admin' && billing.payment_status === 'unpaid'

  async function handleWaiveStorageFees(): Promise<void> {
    if (!billing) return
    setWaivingFees(true)
    try {
      const updated = await billingApi.waiveStorageFees(billing.id, 'Waived by staff')
      setBilling(updated)
      invalidateBillingCaches()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not waive storage fees.')
    } finally {
      setWaivingFees(false)
    }
  }

  async function handleRemoveCharge(chargeId: string): Promise<void> {
    if (!billing) return
    setRemovingChargeId(chargeId)
    try {
      await billingApi.deleteMiscCharge(billing.id, chargeId)
      await refetchCharges()
      await load() // totals changed
      invalidateBillingCaches()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not remove charge.')
    } finally {
      setRemovingChargeId(null)
    }
  }

  async function handleConfirmClaim(claimId: string): Promise<void> {
    setReviewingClaimId(claimId)
    setClaimActionError(null)
    try {
      await paymentClaimApi.confirm(claimId)
      await refetchClaims()
      await load() // the confirmed claim just created a real payment — totals changed
      invalidateBillingCaches()
    } catch (err) {
      setClaimActionError(err instanceof ApiError ? err.message : 'Could not confirm this payment claim.')
    } finally {
      setReviewingClaimId(null)
    }
  }

  async function handleRejectClaim(claimId: string): Promise<void> {
    if (!rejectReason.trim()) return
    setReviewingClaimId(claimId)
    setClaimActionError(null)
    try {
      await paymentClaimApi.reject(claimId, rejectReason.trim())
      await refetchClaims()
      setRejectingClaimId(null)
      setRejectReason('')
      invalidateBillingCaches()
    } catch (err) {
      setClaimActionError(err instanceof ApiError ? err.message : 'Could not reject this payment claim.')
    } finally {
      setReviewingClaimId(null)
    }
  }

  return (
    <div>
      {session?.readOnly && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="warning" icon="eye" title="Read-only session">
            You're viewing this tenant as their Tenant Admin for support. Data is fully visible, but every create, edit, approve, and delete action is disabled. The session ends automatically after 30 minutes or when you exit.
          </Banner>
        </div>
      )}
      {/* Hero */}
      <div className={styles.hero}>
        <div className={styles.heroLeft}>
          <div className={styles.heroIcon}>
            <Icon name="coin" size={28} stroke={2} />
          </div>
          <div>
            <div className={styles.heroTitleRow}>
              <h1 className={styles.heroTitle}>{billing.container_number ?? billing.container_id}</h1>
              <Badge variant={STATUS_VARIANT[billing.payment_status]}>{statusLabel(billing.payment_status)}</Badge>
            </div>
            {billing.billed_at && (
              <div className={styles.heroMeta}>Billed {billing.billed_at.slice(0, 10)}</div>
            )}
          </div>
        </div>
        <div className={styles.heroActions}>
          <ExportButton
            formats={['xlsx', 'csv']}
            onExport={(fmt) => billingApi.export(billing.id, fmt)}
          />
          {isActionable && (
            <Action variant="primary" icon="coin" onClick={() => setShowPaymentModal(true)}>
              Record payment
            </Action>
          )}
          {isStaff && billing.payment_status !== 'cancelled' && billing.payment_status !== 'waived' && (
            <Action variant="secondary" icon="plus" onClick={() => setShowAddChargeModal(true)}>
              Add charge
            </Action>
          )}
          {isCarryoverApplicable && (
            <Action
              variant="secondary"
              onClick={() => {
                void loadCarryovers()
                setShowCarryoverModal(true)
              }}
            >
              Apply carryover
            </Action>
          )}
          {canGenerateRelease && (
            <Action
              variant="secondary"
              icon="file"
              onClick={() => setShowReleaseNoteModal(true)}
            >
              Generate release note
            </Action>
          )}
          {isCancellable && (
            <Action
              variant="danger-outline"
              onClick={() => {
                setCancelError(null)
                setShowCancelModal(true)
              }}
            >
              Cancel billing
            </Action>
          )}
        </div>
      </div>

      {/* Stat cards */}
      <div className={styles.stats}>
        <StatCard label="Total CBM" value={Number(billing.total_cbm).toFixed(3)} />
        <StatCard label="Total due" value={`₦${Number(billing.total_due_ngn).toLocaleString()}`} />
        <StatCard label="Total paid" value={`₦${Number(billing.total_paid_ngn).toLocaleString()}`} />
        <StatCard
          label="Outstanding"
          value={`₦${outstanding.toLocaleString()}`}
        />
      </div>

      {/* Storage fee banner + accrual log */}
      {(Number(billing.storage_fees_ngn) > 0 || billing.release_note_issued_at) && (
        <div className={styles.section}>
          <StorageFeeBanner
            billing={billing}
            storageFees={storageFees}
            canWaive={canWaiveFees}
            onWaive={() => void handleWaiveStorageFees()}
            waiving={waivingFees}
          />
          {storageFees.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <SectionHead title="Storage fee accrual log" />
              <div style={{ marginTop: 8 }}>
                <StorageFeeLog fees={storageFees} />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Breakdown card */}
      <div className={styles.section}>
        <SectionHead title="Billing breakdown" />
        <Card padding={20}>
          <div className={styles.breakdown}>
            <div className={styles.breakdownRow}>
              <span>CBM × rate</span>
              <span>{Number(billing.total_cbm).toFixed(3)} CBM × ${Number(billing.cbm_rate_usd).toFixed(2)} = <Mono>${Number(billing.subtotal_usd).toLocaleString()}</Mono></span>
            </div>
            {/* Per-package-type detail — only worth showing when the tenant
                actually priced this invoice by package type; a flat-rate
                invoice's single line above already says everything. */}
            {billing.cbm_rate_mode === 'per_package_type' && billing.cbm_breakdown && (
              <>
                {(['carton', 'bag', 'bale'] as const).map((bucket) => {
                  const item = billing.cbm_breakdown![bucket]
                  if (Number(item.cbm) <= 0) return null
                  const sym = billing.cbm_rate_currency === 'NGN' ? '₦' : '$'
                  return (
                    <div className={styles.breakdownRow} key={bucket}>
                      <span style={{ paddingLeft: 16, textTransform: 'capitalize' }}>{bucket}s</span>
                      <span>
                        {Number(item.cbm).toFixed(3)} CBM × {sym}{Number(item.rate).toFixed(2)} = <Mono>{sym}{Number(item.subtotal).toLocaleString()}</Mono>
                      </span>
                    </div>
                  )
                })}
              </>
            )}
            <div className={styles.breakdownRow}>
              <span>Exchange rate</span>
              <Mono>₦{Number(billing.dollar_rate).toLocaleString()} / $</Mono>
            </div>
            <div className={styles.breakdownRow}>
              <span>CBM subtotal</span>
              <Mono>₦{Number(billing.subtotal_ngn).toLocaleString()}</Mono>
            </div>
            {/* Itemized by real description inline — not a lump "Misc fees"
                figure a staff member has to scroll down to decode against
                the separate "Miscellaneous charges" table below. */}
            {billing.misc_fees.map((fee, i) => (
              <div className={styles.breakdownRow} key={i}>
                <span>{fee.description}</span>
                <Mono>₦{Number(fee.amount_ngn).toLocaleString()}</Mono>
              </div>
            ))}
            {Number(billing.storage_fees_ngn) > 0 && (
              <div className={styles.breakdownRow}>
                <span>Storage fees</span>
                <Mono>₦{Number(billing.storage_fees_ngn).toLocaleString()}</Mono>
              </div>
            )}
            {Number(billing.carryover_ngn) > 0 && (
              <div className={styles.breakdownRow}>
                <span>Carryover applied</span>
                <Mono>+₦{Number(billing.carryover_ngn).toLocaleString()}</Mono>
              </div>
            )}
            {Number(billing.adjustments_ngn) !== 0 && (
              <div className={styles.breakdownRow}>
                <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>CBM dispute adjustment</span>
                <Mono color="var(--color-success)">−₦{Math.abs(Number(billing.adjustments_ngn)).toLocaleString()}</Mono>
              </div>
            )}
            <div className={`${styles.breakdownRow} ${styles.breakdownTotal}`}>
              <span>Total due</span>
              <Mono>₦{Number(billing.total_due_ngn).toLocaleString()}</Mono>
            </div>
            <div className={styles.breakdownRow}>
              <span style={{ color: 'var(--color-success)' }}>Total paid</span>
              <Mono color="var(--color-success)">−₦{Number(billing.total_paid_ngn).toLocaleString()}</Mono>
            </div>
            <div className={`${styles.breakdownRow} ${styles.breakdownTotal}`}>
              <span style={{ color: Number(billing.outstanding_ngn) > 0 ? 'var(--color-error)' : undefined }}>Outstanding</span>
              <Mono color={Number(billing.outstanding_ngn) > 0 ? 'var(--color-error)' : undefined}>
                ₦{Number(billing.outstanding_ngn).toLocaleString()}
              </Mono>
            </div>
          </div>
        </Card>
      </div>

      {/* Payments table */}
      {billing.payments.length > 0 && (
        <div className={styles.section}>
          <SectionHead title="Payments" sub={`${billing.payments.length} payment(s) recorded`} />
          <Card padding={0}>
            <Table
              columns={[
                { title: 'Amount (₦)', align: 'right' },
                { title: 'Method' },
                { title: 'Reference' },
                { title: 'Confirmed' },
              ]}
              rows={billing.payments.map((p) => ({
                cells: [
                  <Mono key="amount">₦{Number(p.amount_ngn).toLocaleString()}</Mono>,
                  <span key="method">{p.payment_method ?? '—'}</span>,
                  <Mono key="ref">{p.payment_reference ?? '—'}</Mono>,
                  <span key="date">{p.confirmed_at.slice(0, 10)}</span>,
                ],
              }))}
            />
          </Card>
        </div>
      )}

      {/* Payment claims — customer "I've made this payment" submissions awaiting
          staff review. Confirming creates the real payment_record via the same
          confirm_payment() path as "Record payment" above; rejecting requires a
          reason and never touches billing totals. */}
      {paymentClaims.length > 0 && (
        <div className={styles.section}>
          <SectionHead
            title="Payment claims"
            sub={`${paymentClaims.filter((c) => c.status === 'pending').length} pending review`}
          />
          {claimActionError && (
            <div style={{ marginBottom: 12 }}>
              <Banner variant="error" title="Action failed">{claimActionError}</Banner>
            </div>
          )}
          <Card padding={0}>
            <Table
              columns={[
                { title: 'Amount (₦)', align: 'right' },
                { title: 'Submitted' },
                { title: 'Evidence' },
                { title: 'Status' },
                ...(isStaff ? [{ title: '', width: '220px' }] : []),
              ]}
              rows={paymentClaims.map((claim) => ({
                cells: [
                  <Mono key="amount">₦{Number(claim.amount_ngn).toLocaleString()}</Mono>,
                  <span key="date">{claim.submitted_at.slice(0, 10)}</span>,
                  <Button
                    key="evidence"
                    variant="ghost"
                    size="sm"
                    icon="eye"
                    onClick={() =>
                      void paymentClaimApi
                        .getEvidenceUrl(claim.id)
                        .then((r) => window.open(r.url, '_blank', 'noopener'))
                        .catch((err: unknown) =>
                          setClaimActionError(err instanceof ApiError ? err.message : 'Could not open evidence.'),
                        )
                    }
                  >
                    {claim.evidence_file_name}
                  </Button>,
                  <Badge
                    key="status"
                    variant={claim.status === 'confirmed' ? 'success' : claim.status === 'rejected' ? 'error' : 'warning'}
                  >
                    {claim.status === 'pending' ? 'Pending' : claim.status === 'confirmed' ? 'Confirmed' : 'Rejected'}
                  </Badge>,
                  ...(isStaff
                    ? [
                        claim.status === 'pending' ? (
                          rejectingClaimId === claim.id ? (
                            <div key="reject" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                              <Field
                                name="reject_reason"
                                placeholder="Reason for rejecting"
                                value={rejectReason}
                                onChange={(e) => setRejectReason(e.target.value)}
                              />
                              <Button
                                variant="danger"
                                size="sm"
                                loading={reviewingClaimId === claim.id}
                                disabled={!rejectReason.trim()}
                                onClick={() => void handleRejectClaim(claim.id)}
                              >
                                Confirm reject
                              </Button>
                              <Button variant="ghost" size="sm" onClick={() => { setRejectingClaimId(null); setRejectReason('') }}>
                                Cancel
                              </Button>
                            </div>
                          ) : (
                            <div key="actions" style={{ display: 'flex', gap: 6 }}>
                              <Button
                                variant="primary"
                                size="sm"
                                loading={reviewingClaimId === claim.id}
                                onClick={() => void handleConfirmClaim(claim.id)}
                              >
                                Confirm
                              </Button>
                              <Button variant="secondary" size="sm" onClick={() => setRejectingClaimId(claim.id)}>
                                Reject
                              </Button>
                            </div>
                          )
                        ) : (
                          <span key="reviewed" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
                            {claim.status === 'rejected' ? claim.rejection_reason : 'Payment recorded'}
                          </span>
                        ),
                      ]
                    : []),
                ],
              }))}
            />
          </Card>
        </div>
      )}

      {/* Misc charges — full rows with ids so admin can remove (7.2 prototype) */}
      {(miscCharges.length > 0 || billing.misc_fees.length > 0) && (
        <div className={styles.section}>
          <SectionHead
            title="Miscellaneous charges"
            sub={miscCharges.length > 0 ? `${miscCharges.length} charge(s)` : undefined}
          />
          <Card padding={0}>
            <Table
              columns={[
                { title: 'Charge' },
                { title: 'Type' },
                { title: 'Amount (₦)', align: 'right' },
                ...(canRemoveCharge ? [{ title: '', width: '48px' }] : []),
              ]}
              rows={(miscCharges.length > 0
                ? miscCharges.map((c) => ({
                    cells: [
                      <span key="desc">{c.description}</span>,
                      <span key="type" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{c.charge_type.replace(/_/g, ' ')}</span>,
                      <Mono key="amt">₦{Number(c.amount_ngn).toLocaleString()}</Mono>,
                      ...(canRemoveCharge
                        ? [
                            <Button
                              key="rm"
                              variant="ghost"
                              size="sm"
                              icon="x"
                              aria-label="Remove charge"
                              loading={removingChargeId === c.id}
                              onClick={() => void handleRemoveCharge(c.id)}
                            />,
                          ]
                        : []),
                    ],
                  }))
                : billing.misc_fees.map((f) => ({
                    cells: [
                      <span key="desc">{f.description}</span>,
                      <span key="type" />,
                      <Mono key="amt">₦{Number(f.amount_ngn).toLocaleString()}</Mono>,
                      ...(canRemoveCharge ? [<span key="rm" />] : []),
                    ],
                  })))}
            />
          </Card>
        </div>
      )}

      {/* Active disputes */}
      {billing._active_disputes.length > 0 && (
        <div className={styles.section}>
          <SectionHead title="CBM disputes" />
          {billing._active_disputes.map((d) => (
            <DisputeCard key={d.id} dispute={d} role={role} onUpdated={handleDisputeUpdated} />
          ))}
        </div>
      )}

      {/* Back link */}
      <div className={styles.backLink}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate('/billing')}>
          Back to billing
        </Button>
      </div>

      {/* Modals */}
      {showAddChargeModal && (
        <AddChargeModal
          billing={billing}
          onCancel={() => setShowAddChargeModal(false)}
          onSuccess={() => {
            setShowAddChargeModal(false)
            void refetchCharges()
            void load() // totals changed
            invalidateBillingCaches()
          }}
        />
      )}
      {showPaymentModal && (
        <RecordPaymentModal
          billing={billing}
          onCancel={() => setShowPaymentModal(false)}
          onSuccess={() => {
            setShowPaymentModal(false)
            void load()
            invalidateBillingCaches()
          }}
        />
      )}

      {showCancelModal && (
        <CancelBillingModal
          billingId={billing.id}
          error={cancelError}
          onCancel={() => setShowCancelModal(false)}
          onSuccess={(updated) => {
            setShowCancelModal(false)
            setBilling(updated)
            invalidateBillingCaches()
          }}
        />
      )}

      {showCarryoverModal && (
        <ApplyCarryoverModal
          billing={billing}
          carryovers={carryovers}
          onCancel={() => setShowCarryoverModal(false)}
          onSuccess={() => {
            setShowCarryoverModal(false)
            void load()
            invalidateBillingCaches()
          }}
        />
      )}

      {showReleaseNoteModal && (
        <GenerateReleaseNoteModal
          billing={billing}
          onCancel={() => setShowReleaseNoteModal(false)}
          onSuccess={() => {
            setShowReleaseNoteModal(false)
            invalidateBillingCaches()
            // Ground-truth gap found live: this navigates straight to the
            // release-notes list, but nothing invalidated its query cache —
            // with the 3-minute default staleTime (lib/queryClient.ts), a
            // list already fetched once this session kept showing
            // pre-generation data, hiding the note just created.
            void qc.invalidateQueries({ queryKey: releaseNoteKeys.all })
            navigate('/release-notes')
          }}
        />
      )}
    </div>
  )
}
