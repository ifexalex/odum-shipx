import { useState, type JSX } from 'react'
import { ApiError } from '../../../api/client'
import { disputeApi, type CBMDispute, type ResolveCBMDisputeInput } from '../../../api/billing'
import {
  canAcknowledgeDispute,
  canRejectDispute,
  canResolveDispute,
  isTerminalDisputeStatus,
} from '../../../api/billingRules'
import { Action, Banner, Button, DialogGuard, Field, Mono, StatusBadge } from '../../../design/components'
import { RecordLink } from '../../../shell/RecordLink'
import styles from '../BillingDetail.module.css'
import { formatCbm, formatDate } from '../../../lib/format'
import { toast } from '../../../design/toast'

// ---------------------------------------------------------------------------
// DisputeSLA
// ---------------------------------------------------------------------------

function _slaCountdown(
  deadlineIso: string | null,
): { label: string; overdue: boolean; urgent: boolean } | null {
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

export interface DisputeSLAProps {
  dispute: CBMDispute
}

export function DisputeSLA({ dispute }: DisputeSLAProps): JSX.Element | null {
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
      deadline: ['investigating', 'escalated_china', 'escalated'].includes(status)
        ? investigate_due_by
        : null,
      done: [
        'escalated_china',
        'escalated',
        'resolved_adjusted',
        'resolved_no_change',
        'closed',
      ].includes(status),
      ts: auto_escalated_at,
    },
    {
      label: 'Resolve',
      deadline: ['investigating', 'escalated_china', 'escalated'].includes(status)
        ? resolve_due_by
        : null,
      done: ['resolved_adjusted', 'resolved_no_change', 'closed'].includes(status),
    },
  ]

  return (
    <div style={{ marginTop: 'var(--space-2)', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      {stages.map((stage) => {
        const cd = stage.done ? null : _slaCountdown(stage.deadline)
        const color = stage.done
          ? 'var(--color-ink-4)'
          : cd?.overdue
            ? 'var(--color-error)'
            : cd?.urgent
              ? 'var(--color-warning)'
              : 'var(--color-ink-4)'

        return (
          <div
            key={stage.label}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              fontSize: 'var(--text-xs)',
              color,
            }}
          >
            <span style={{ fontWeight: 600, minWidth: 80 }}>{stage.label}</span>
            {stage.done ? (
              <span>{stage.ts ? `✓ ${formatDate(stage.ts)}` : '✓ Done'}</span>
            ) : cd ? (
              <span>{cd.overdue ? '⚠ Overdue' : `${cd.label} remaining`}</span>
            ) : stage.deadline ? (
              <span>Due {formatDate(stage.deadline)}</span>
            ) : (
              <span style={{ color: 'var(--color-ink-4)' }}>—</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ResolveDisputeModal
// ---------------------------------------------------------------------------

export interface ResolveDisputeModalProps {
  dispute: CBMDispute
  onCancel: () => void
  onSuccess: (updated: CBMDispute) => void
}

export function ResolveDisputeModal({
  dispute,
  onCancel,
  onSuccess,
}: ResolveDisputeModalProps): JSX.Element {
  const [outcome, setOutcome] = useState<'resolved_adjusted' | 'resolved_no_change'>(
    'resolved_no_change',
  )
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
      toast.success('Dispute resolved')
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve dispute.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit =
    notes.trim().length > 0 &&
    (outcome === 'resolved_no_change' ||
      (outcome === 'resolved_adjusted' && correctedCbm.trim().length > 0))

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Resolve CBM dispute</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">
              {error}
            </Banner>
          </div>
        )}
        <div className={styles.outcomeToggle}>
          <Button
            variant={outcome === 'resolved_no_change' ? 'primary' : 'secondary'}
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
            placeholder={`Original: ${formatCbm(dispute.original_cbm)}`}
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
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Action
            variant="primary"
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
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

export interface DisputeCardProps {
  dispute: CBMDispute
  role: string
  onUpdated: (updated: CBMDispute) => void
}

export function DisputeCard({ dispute, role, onUpdated }: DisputeCardProps): JSX.Element {
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
      toast.success('Dispute acknowledged')
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
      toast.success('Dispute rejected')
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
          <StatusBadge kind="dispute" status={dispute.status} />
          {!isTerminalDisputeStatus(dispute.status) && <DisputeSLA dispute={dispute} />}
        </div>
        <div className={styles.disputeNumbers}>
          {dispute.original_cbm && (
            <span>
              Original CBM: <Mono>{formatCbm(dispute.original_cbm)}</Mono>
            </span>
          )}
          {dispute.customer_measured_cbm && (
            <span>
              Customer claimed: <Mono>{formatCbm(dispute.customer_measured_cbm)}</Mono>
            </span>
          )}
          {dispute.corrected_cbm && (
            <span>
              Corrected: <Mono>{formatCbm(dispute.corrected_cbm)}</Mono>
            </span>
          )}
        </div>
      </div>

      {dispute.reason && <p className={styles.disputeReason}>{dispute.reason}</p>}

      {error && (
        <div className={styles.disputeError}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      <div className={styles.disputeFooter}>
        <RecordLink to={`/billing/disputes/${dispute.id}`}>
          View measurement breakdown
        </RecordLink>

        {!isTerminalDisputeStatus(dispute.status) && (
          <div className={styles.disputeActions}>
            {canAcknowledgeDispute(dispute, r) && (
              <Button
                variant="secondary"
                size="sm"
                loading={acknowledging}
                onClick={() => void handleAcknowledge()}
              >
                Acknowledge
              </Button>
            )}
            {canResolveDispute(dispute, r) && (
              <Button variant="primary" size="sm" onClick={() => setShowResolve(true)}>
                Resolve
              </Button>
            )}
            {canRejectDispute(dispute, r) && rejectingReason === null && (
              <Button variant="danger-ghost" size="sm" onClick={() => setRejectingReason('')}>
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
                  <Button variant="ghost" size="sm" onClick={() => setRejectingReason(null)}>
                    Cancel
                  </Button>
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
      </div>

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
