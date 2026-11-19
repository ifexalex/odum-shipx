import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { refundsApi, type AccountsReviewInput, type ApproveRefundInput, type Refund } from '../../api/refunds'
import { refundKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import {
  approvalLevelLabel,
  canApproveRefund,
  canRejectRefund,
  canReviewRefund,
  customerChoiceLabel,
  isTerminalRefundStatus,
  refundTypeLabel,
} from '../../api/refundsRules'
import { useSession } from '../../auth/useSession'
import { Action, Banner, Button, Card, DialogGuard, Field, Icon, Kvp, Mono, StatCard, StatusBadge, RadioGroup } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './RefundDetail.module.css'
import { formatDate, formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// RefundStepper
// ---------------------------------------------------------------------------

interface StepDef {
  label: string
  sub?: string
}

function buildSteps(refund: Refund): { steps: StepDef[]; activeIndex: number; isRejected: boolean } {
  const isRejected = refund.status === 'rejected'

  const steps: StepDef[] = [
    { label: 'Accounts review', sub: refund.debt_check_notes ? (refund.debt_check_passed ? '✓ Debt clear' : '✗ Debt found') : undefined },
    {
      label: refund.approval_level === 'head_of_finance' ? 'Head of finance' : 'Manager approval',
      sub: refund.approval_level === 'head_of_finance' ? 'Tenant admin required' : undefined,
    },
    { label: refund.customer_choice === 'credit_next_shipment' ? 'Credit applied' : 'Processed' },
  ]

  let activeIndex = 0
  if (refund.status === 'pending_approval' || refund.status === 'accounts_reviewed') activeIndex = 1
  if (refund.status === 'processed' || refund.status === 'applied_as_credit' || refund.status === 'approved') activeIndex = 2
  if (isRejected) {
    // Active index is where it was rejected
    activeIndex = refund.debt_check_passed === false ? 0 : 1
  }

  return { steps, activeIndex, isRejected }
}

function RefundStepper({ refund }: { refund: Refund }): JSX.Element {
  const { steps, activeIndex, isRejected } = buildSteps(refund)
  const isTerminal = isTerminalRefundStatus(refund.status) && !isRejected

  return (
    <div className={styles.stepperWrap} data-scroll-strip="">
      <div className={styles.stepper}>
        {steps.map((step, i) => {
          const done = isTerminal ? i <= activeIndex : i < activeIndex
          const isCurrent = i === activeIndex
          const rejected = isRejected && isCurrent

          return (
            <div
              key={step.label}
              className={[
                styles.step,
                done ? styles.stepDone : '',
                isCurrent && !rejected ? styles.stepActive : '',
                rejected ? styles.stepRejected : '',
              ].join(' ')}
            >
              <div className={styles.stepDot}>
                {done && <Icon name="check" size={12} color="#fff" />}
                {rejected && <Icon name="x" size={12} color="#fff" />}
              </div>
              <span className={styles.stepLabel}>{step.label}</span>
              {step.sub && <span className={styles.approvalNote}>{step.sub}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AccountsReviewModal
// ---------------------------------------------------------------------------

interface AccountsReviewModalProps {
  refund: Refund
  onCancel: () => void
  onSuccess: (updated: Refund) => void
}

function AccountsReviewModal({ refund, onCancel, onSuccess }: AccountsReviewModalProps): JSX.Element {
  const [passed, setPassed] = useState(true)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: AccountsReviewInput = { debt_check_passed: passed, debt_check_notes: notes }
      const updated = await refundsApi.review(refund.id, body)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not complete review.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Accounts review</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <Banner variant="info">
          Check customer debt records (unpaid billing, outstanding carryovers) before advancing this refund.
        </Banner>
        <RadioGroup
          label="Debt check"
          name="debt_check"
          value={passed ? 'passed' : 'failed'}
          onChange={(v) => setPassed(v === 'passed')}
          options={[
            { value: 'passed', label: 'Debt check passed', hint: 'Advance to manager approval.' },
            { value: 'failed', label: 'Debt check failed', hint: 'Reject, to offset the debt.' },
          ]}
        />
        <Field
          label="Review notes"
          name="debt_check_notes"
          required
          multiline
          placeholder={passed ? 'e.g. No outstanding debt found' : 'e.g. Outstanding balance of ₦12,000 on container ACME-001'}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button
            variant={passed ? 'primary' : 'danger'}
            loading={submitting}
            disabled={!notes.trim()}
            onClick={() => void handleSubmit()}
          >
            {passed ? 'Advance to approval' : 'Reject — debt offset'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ApproveModal
// ---------------------------------------------------------------------------

interface ApproveModalProps {
  refund: Refund
  role: string
  onCancel: () => void
  onSuccess: (updated: Refund) => void
}

function ApproveModal({ refund, role, onCancel, onSuccess }: ApproveModalProps): JSX.Element {
  const [amountApproved, setAmountApproved] = useState(refund.amount_requested_ngn)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isStaff = role === 'nigeria_office_staff'
  const approvalLevel = refund.approval_level ?? 'manager'
  const enteredAmount = Number(amountApproved)
  const requestedAmount = Number(refund.amount_requested_ngn)
  const isPartial = enteredAmount > 0 && enteredAmount < requestedAmount

  // Threshold from backend config. May be null (config read failed) or undefined
  // (refund arrived via route state from the list, which omits `threshold`) — in
  // both cases skip the client-side gate and let the server enforce the limit.
  const th = refund.threshold ?? null
  const staffLimitNgn = th?.staff_limit_ngn ?? 0
  const exceedsThreshold = isStaff && th !== null && staffLimitNgn > 0 && enteredAmount > staffLimitNgn
  const staffLimitUsd = th?.staff_limit_usd ?? 0
  const hof_blocked = approvalLevel === 'head_of_finance' && isStaff

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: ApproveRefundInput = { amount_approved_ngn: amountApproved, approval_level: approvalLevel }
      const updated = await refundsApi.approve(refund.id, body)
      onSuccess(updated)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError(`Approval limit exceeded. Escalate to tenant admin — staff limit is ${formatNgn(staffLimitNgn)} ($${staffLimitUsd} USD).`)
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not approve refund.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  // Meter percentage — cap at 100% for display; show overflow state when >100%
  const meterPct = staffLimitNgn > 0 ? Math.min((enteredAmount / staffLimitNgn) * 100, 100) : 0
  const meterColor = exceedsThreshold ? 'var(--color-error)' : 'var(--color-success)'

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Approve refund</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}

        {hof_blocked && (
          <div className={styles.modalBanner}>
            <Banner variant="error">
              This refund type requires head-of-finance (tenant admin) approval. You cannot approve it as staff.
            </Banner>
          </div>
        )}

        {isPartial && (
          <div className={styles.modalBanner}>
            <Banner variant="info">
              Partial approval: {formatNgn(enteredAmount)} of {formatNgn(requestedAmount)} requested.
            </Banner>
          </div>
        )}

        <Field
          label="Amount to approve (₦)"
          name="amount_approved_ngn"
          required
          type="number"
          value={amountApproved}
          onChange={(e) => setAmountApproved(e.target.value)}
        />

        {/* Staff approval threshold meter */}
        {isStaff && th !== null && staffLimitNgn > 0 && (
          <div className={styles.thresholdMeter}>
            <div className={styles.thresholdMeterBar}>
              <div
                className={styles.thresholdMeterFill}
                style={{ width: `${meterPct}%`, background: meterColor }}
                role="meter"
                aria-valuenow={enteredAmount}
                aria-valuemin={0}
                aria-valuemax={staffLimitNgn}
                aria-label="Staff approval limit"
              />
            </div>
            <div className={styles.thresholdMeterLabel}>
              {exceedsThreshold ? (
                <span style={{ color: 'var(--color-error)', fontWeight: 600 }}>
                  {formatNgn(enteredAmount)} exceeds staff limit of {formatNgn(staffLimitNgn)} (${staffLimitUsd} USD)
                </span>
              ) : (
                <span style={{ color: 'var(--color-ink-4)' }}>
                  {formatNgn(enteredAmount)} of {formatNgn(staffLimitNgn)} staff limit (${staffLimitUsd} USD)
                </span>
              )}
            </div>
            {exceedsThreshold && (
              <Banner variant="warning" title="Exceeds staff approval limit">
                This amount requires escalation to the Head of Finance (tenant admin). You cannot approve it as staff.
              </Banner>
            )}
          </div>
        )}

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button
            variant="primary"
            loading={submitting}
            disabled={enteredAmount <= 0 || hof_blocked || exceedsThreshold}
            onClick={() => void handleSubmit()}
          >
            Confirm approval
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// RejectConfirmModal
// ---------------------------------------------------------------------------

interface RejectModalProps {
  onCancel: () => void
  onSuccess: (updated: Refund) => void
  refundId: string
}

function RejectModal({ onCancel, onSuccess, refundId }: RejectModalProps): JSX.Element {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const updated = await refundsApi.reject(refundId, reason)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reject refund.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Reject refund request</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <Field
          label="Rejection reason"
          name="rejection_reason"
          required
          multiline
          placeholder="Why is this refund request being rejected?"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="danger" loading={submitting} disabled={!reason.trim()} onClick={() => void handleSubmit()}>
            Confirm rejection
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function RefundDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'

  const qc = useQueryClient()
  const stateRefund = (location.state as { refund?: Refund } | null)?.refund ?? null
  const { data: refund = null, isLoading: loading, error: loadError } = useQuery({
    queryKey: refundKeys.detail(id ?? ''),
    queryFn: () => refundsApi.get(id!),
    enabled: !!id,
    ...(stateRefund ? { initialData: stateRefund } : {}),
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(refund ? refundTypeLabel(refund.refund_type) : null)
  const applyUpdated = (updated: Refund): void => {
    qc.setQueryData(refundKeys.detail(id ?? ''), updated)
  }

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load this refund request.'
    : null

  const [showReview, setShowReview] = useState(false)
  const [showApprove, setShowApprove] = useState(false)
  const [showReject, setShowReject] = useState(false)


  if (loading && !refund) return <div className={styles.loadingState}>Loading refund…</div>
  if (error && !refund) {
    return (
      <div className={styles.loadingState}>
        <Banner variant="error" title="Couldn't load this refund">{error ?? 'Not found.'}</Banner>
      </div>
    )
  }
  if (!refund) return <></>

  const r = role as Parameters<typeof canReviewRefund>[1]
  const showReviewBtn = canReviewRefund(refund, r)
  const showApproveBtn = canApproveRefund(refund, r)
  const showRejectBtn = canRejectRefund(refund, r)

  return (
    <div>
      {/* Hero */}
      <div className={styles.hero}>
        <div className={styles.heroLeft}>
          <div className={styles.heroIcon}>
            <Icon name="card" size={28} stroke={2} />
          </div>
          <div>
            <div className={styles.heroTitleRow}>
              <h1 className={styles.heroTitle}>{refundTypeLabel(refund.refund_type)}</h1>
              <StatusBadge kind="refund" status={refund.status} />
            </div>
            <div className={styles.heroMeta}>
              <span>Requested {formatDate(refund.created_at)}</span>
              {refund.approval_level && (
                <span> · {approvalLevelLabel(refund.approval_level)}</span>
              )}
            </div>
          </div>
        </div>
        {!isTerminalRefundStatus(refund.status) && (
          <div className={styles.heroActions}>
            {showReviewBtn && (
              <Action variant="primary" icon="check" onClick={() => setShowReview(true)}>
                Accounts review
              </Action>
            )}
            {showApproveBtn && (
              <Action variant="primary" icon="check" onClick={() => setShowApprove(true)}>
                Approve
              </Action>
            )}
            {showRejectBtn && (
              <Action variant="danger-ghost" icon="x" onClick={() => setShowReject(true)}>
                Reject
              </Action>
            )}
          </div>
        )}
      </div>

      {/* Status stepper */}
      <div className={styles.section}>
        <Card padding="default">
          <SectionHead title="Approval progress" />
          <RefundStepper refund={refund} />
        </Card>
      </div>

      {/* Rejection detail */}
      {refund.status === 'rejected' && refund.rejection_reason && (
        <div className={styles.section}>
          <Banner variant="error" title="Rejection reason">{refund.rejection_reason}</Banner>
        </div>
      )}

      {/* Debt check result */}
      {refund.debt_check_notes && (
        <div className={styles.section}>
          <Banner
            variant={refund.debt_check_passed ? 'success' : 'warning'}
            title={refund.debt_check_passed ? 'Debt check passed' : 'Outstanding debt found'}
          >
            {refund.debt_check_notes}
          </Banner>
        </div>
      )}

      {/* Stats */}
      <div className={styles.statsRow}>
        <StatCard label="Requested" value={formatNgn(refund.amount_requested_ngn)} />
        <StatCard
          label="Approved"
          value={refund.amount_approved_ngn ? formatNgn(refund.amount_approved_ngn) : '—'}
        />
        <StatCard label="Payout method" value={customerChoiceLabel(refund.customer_choice)} />
        {/* A credit is spent only as far as each invoice needs it, so part of one can still be unused. */}
        {refund.customer_choice === 'credit_next_shipment' && refund.amount_approved_ngn && (
          <StatCard
            label="Credit used"
            value={`${formatNgn(refund.credit_applied_ngn ?? '0')} of ${formatNgn(refund.amount_approved_ngn)}`}
          />
        )}
      </div>

      {/* Details card */}
      <div className={styles.section}>
        <SectionHead title="Request details" />
        <Card padding="default">
          <Kvp label="Refund type" value={refundTypeLabel(refund.refund_type)} />
          {refund.reason && <Kvp label="Reason" value={refund.reason} />}
          {refund.customer_id && <Kvp label="Customer ID" value={<Mono>{refund.customer_id}</Mono>} />}
          {refund.billing_id && <Kvp label="Linked billing" value={<Mono>{refund.billing_id}</Mono>} />}
          {refund.damage_claim_id && (
            <Kvp label="Linked claim" value={<Mono>{refund.damage_claim_id}</Mono>} />
          )}
          <Kvp
            label="Customer preference"
            value={customerChoiceLabel(refund.customer_choice)}
            divider={Boolean(refund.bank_details)}
          />
          {refund.bank_details && (
            <>
              <Kvp label="Bank" value={refund.bank_details.bank_name ?? '—'} />
              <Kvp label="Account number" value={<Mono>{refund.bank_details.account_number ?? '—'}</Mono>} />
              <Kvp label="Account name" value={refund.bank_details.account_name ?? '—'} divider={false} />
            </>
          )}
        </Card>
      </div>

      {/* Modals */}
      {showReview && (
        <AccountsReviewModal
          refund={refund}
          onCancel={() => setShowReview(false)}
          onSuccess={(updated) => { setShowReview(false); applyUpdated(updated) }}
        />
      )}
      {showApprove && (
        <ApproveModal
          refund={refund}
          role={role}
          onCancel={() => setShowApprove(false)}
          onSuccess={(updated) => { setShowApprove(false); applyUpdated(updated) }}
        />
      )}
      {showReject && (
        <RejectModal
          refundId={refund.id}
          onCancel={() => setShowReject(false)}
          onSuccess={(updated) => { setShowReject(false); applyUpdated(updated) }}
        />
      )}
    </div>
  )
}
