import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { paymentClaimApi, type PaymentClaim } from '../../../api/billing'
import { ApiError } from '../../../api/client'
import { billingKeys } from '../../../api/keys'
import { Banner, Button, ConfirmDialog, Field, Modal, Mono, Table, StatusBadge } from '../../../design/components'
import { formatDate, formatNgn } from '../../../lib/format'
import { Section } from '../../../shell/Section'
import { toast } from '../../../design/toast'

interface PaymentClaimsSectionProps {
  billingId: string
  /** Staff confirm or reject; others only see the list. */
  isStaff: boolean
  /** Called after a claim is confirmed or rejected, to refresh the invoice. */
  onChanged: () => void
}

/**
 * Payment claims — customer "I've made this payment" submissions awaiting staff review.
 * Confirming creates the real payment_record via the same confirm_payment() path as "Record payment";
 * rejecting requires a reason and never touches billing totals.
 */
export function PaymentClaimsSection({
  billingId,
  isStaff,
  onChanged,
}: PaymentClaimsSectionProps): JSX.Element | null {
  // Customer-submitted "I've made this payment" claims for this billing —
  // the staff-side half of the manual-bank-transfer confirmation flow.
  const { data: paymentClaims = [], refetch: refetchClaims } = useQuery({
    queryKey: [...billingKeys.detail(billingId), 'payment-claims'],
    queryFn: () => paymentClaimApi.listForBilling(billingId),
    staleTime: 30 * 1000,
  })
  const [reviewingClaimId, setReviewingClaimId] = useState<string | null>(null)
  const [confirmingClaim, setConfirmingClaim] = useState<PaymentClaim | null>(null)
  const [rejectingClaim, setRejectingClaim] = useState<PaymentClaim | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [claimActionError, setClaimActionError] = useState<string | null>(null)

  async function handleConfirmClaim(claimId: string): Promise<void> {
    setReviewingClaimId(claimId)
    setClaimActionError(null)
    try {
      await paymentClaimApi.confirm(claimId)
      toast.success('Payment confirmed')
      setConfirmingClaim(null)
      await refetchClaims()
      onChanged()
    } catch (err) {
      setConfirmingClaim(null)
      setClaimActionError(
        err instanceof ApiError ? err.message : 'Could not confirm this payment claim.',
      )
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
      toast.success('Payment claim rejected')
      await refetchClaims()
      setRejectingClaim(null)
      setRejectReason('')
      onChanged()
    } catch (err) {
      setClaimActionError(
        err instanceof ApiError ? err.message : 'Could not reject this payment claim.',
      )
    } finally {
      setReviewingClaimId(null)
    }
  }

  if (paymentClaims.length === 0) return null
  const pendingCount = paymentClaims.filter((c) => c.status === 'pending').length

  return (
    <>
      <Section
        title="Payment claims"
        sub={`${pendingCount} pending review`}
        flush
      >
        {claimActionError && (
          <div style={{ padding: 'var(--space-3) var(--space-5) 0' }}>
            <Banner variant="error" title="Action failed" onDismiss={() => setClaimActionError(null)}>
              {claimActionError}
            </Banner>
          </div>
        )}
        <Table
          columns={[
            { title: 'Amount (₦)', type: 'money' as const },
            { title: 'Submitted', type: 'date' as const },
            { title: 'Evidence & note' },
            { title: 'Status', type: 'status' as const },
            ...(isStaff ? [{ title: '', type: 'action' as const, width: '180px' }] : []),
          ]}
          rows={paymentClaims.map((claim) => ({
            cells: [
              <Mono key="amount">{formatNgn(claim.amount_ngn)}</Mono>,
              <span key="date">{formatDate(claim.submitted_at)}</span>,
              <div key="evidence" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 'var(--space-0-5)' }}>
                <Button
                  variant="ghost"
                  size="sm"
                  icon="eye"
                  onClick={() =>
                    void paymentClaimApi
                      .getEvidenceUrl(claim.id)
                      .then((r) => window.open(r.url, '_blank', 'noopener'))
                      .catch((err: unknown) =>
                        setClaimActionError(
                          err instanceof ApiError ? err.message : 'Could not open evidence.',
                        ),
                      )
                  }
                >
                  {claim.evidence_file_name}
                </Button>
                {claim.customer_note && (
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', paddingLeft: 'var(--space-3)' }}>
                    “{claim.customer_note}”
                  </span>
                )}
              </div>,
              <StatusBadge key="status" kind="paymentClaim" status={claim.status} audience={isStaff ? 'staff' : 'customer'} />,
              ...(isStaff
                ? [
                    claim.status === 'pending' ? (
                      <div key="actions" style={{ display: 'flex', gap: 'var(--space-2)' }}>
                        <Button
                          variant="primary"
                          size="sm"
                          loading={reviewingClaimId === claim.id}
                          onClick={() => setConfirmingClaim(claim)}
                        >
                          Confirm
                        </Button>
                        <Button
                          variant="danger-ghost"
                          size="sm"
                          onClick={() => {
                            setRejectReason('')
                            setClaimActionError(null)
                            setRejectingClaim(claim)
                          }}
                        >
                          Reject
                        </Button>
                      </div>
                    ) : (
                      <span key="reviewed" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                        {claim.status === 'rejected' ? claim.rejection_reason : 'Payment recorded'}
                      </span>
                    ),
                  ]
                : []),
            ],
          }))}
        />
      </Section>

      <ConfirmDialog
        open={Boolean(confirmingClaim)}
        title="Confirm bank transfer payment?"
        confirmLabel="Confirm payment"
        undo="This records a real payment against the invoice and reduces the customer's outstanding balance."
        busy={Boolean(confirmingClaim && reviewingClaimId === confirmingClaim.id)}
        onConfirm={async () => {
          if (confirmingClaim) await handleConfirmClaim(confirmingClaim.id)
        }}
        onCancel={() => setConfirmingClaim(null)}
      >
        {confirmingClaim && (
          <>
            Record <strong>{formatNgn(confirmingClaim.amount_ngn)}</strong> from receipt{' '}
            <Mono>{confirmingClaim.evidence_file_name}</Mono>
            {confirmingClaim.customer_note ? ` (Note: “${confirmingClaim.customer_note}”)` : ''}. Make sure
            funds have settled in your bank account before confirming.
          </>
        )}
      </ConfirmDialog>

      <Modal
        open={Boolean(rejectingClaim)}
        onClose={() => {
          setRejectingClaim(null)
          setRejectReason('')
        }}
        title="Reject payment claim"
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setRejectingClaim(null)
                setRejectReason('')
              }}
              disabled={Boolean(rejectingClaim && reviewingClaimId === rejectingClaim.id)}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={Boolean(rejectingClaim && reviewingClaimId === rejectingClaim.id)}
              disabled={!rejectReason.trim() || Boolean(rejectingClaim && reviewingClaimId === rejectingClaim.id)}
              onClick={() => rejectingClaim && void handleRejectClaim(rejectingClaim.id)}
            >
              Confirm reject
            </Button>
          </>
        }
      >
        {rejectingClaim && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)' }}>
              Rejecting <strong>{formatNgn(rejectingClaim.amount_ngn)}</strong> ({rejectingClaim.evidence_file_name})
              notifies the customer with your reason and leaves the invoice balance unchanged.
            </p>
            <Field
              label="Reason for rejecting"
              name="reject_reason"
              required
              multiline
              placeholder="Reason for rejecting"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
          </div>
        )}
      </Modal>
    </>
  )
}
