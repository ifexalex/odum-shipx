import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { paymentClaimApi } from '../../../api/billing'
import { ApiError } from '../../../api/client'
import { billingKeys } from '../../../api/keys'
import {  Banner, Button, Card, Field, Mono, Table, StatusBadge } from '../../../design/components'
import { formatDate, formatNgn } from '../../../lib/format'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../BillingDetail.module.css'
import { toast } from '../../../design/toast'

interface PaymentClaimsSectionProps {
  billingId: string
  /** Staff confirm or reject; others only see the list. */
  isStaff: boolean
  /** Called after a claim is confirmed or rejected, to refresh the invoice. */
  onChanged: () => void
}

/**
 * Payment claims — customer "I've made this payment" submissions awaiting staff review. Confirming creates the real payment_record via the same confirm_payment() path as "Record payment" above; rejecting requires a reason and never touches billing totals.
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
  const [rejectingClaimId, setRejectingClaimId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [claimActionError, setClaimActionError] = useState<string | null>(null)

  async function handleConfirmClaim(claimId: string): Promise<void> {
    setReviewingClaimId(claimId)
    setClaimActionError(null)
    try {
      await paymentClaimApi.confirm(claimId)
      toast.success('Payment confirmed')
      await refetchClaims()
      onChanged()
    } catch (err) {
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
      setRejectingClaimId(null)
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
  return (
    <div className={styles.section}>
      <SectionHead
        title="Payment claims"
        sub={`${paymentClaims.filter((c) => c.status === 'pending').length} pending review`}
      />
      {claimActionError && (
        <div style={{ marginBottom: 'var(--space-3)' }}>
          <Banner variant="error" title="Action failed">
            {claimActionError}
          </Banner>
        </div>
      )}
      <Card padding="none">
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
              <Mono key="amount">{formatNgn(claim.amount_ngn)}</Mono>,
              <span key="date">{formatDate(claim.submitted_at)}</span>,
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
                      setClaimActionError(
                        err instanceof ApiError ? err.message : 'Could not open evidence.',
                      ),
                    )
                }
              >
                {claim.evidence_file_name}
              </Button>,
              <StatusBadge key="status" kind="paymentClaim" status={claim.status} audience={isStaff ? 'staff' : 'customer'} />,
              ...(isStaff
                ? [
                    claim.status === 'pending' ? (
                      rejectingClaimId === claim.id ? (
                        <div
                          key="reject"
                          style={{
                            display: 'flex',
                            gap: 'var(--space-2)',
                            alignItems: 'center',
                          }}
                        >
                          <Field
                            label="Reason for rejecting"
                            hideLabel
                            name="reject_reason"
                            placeholder="Reason for rejecting"
                            value={rejectReason}
                            onChange={(e) => setRejectReason(e.target.value)}
                          />
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setRejectingClaimId(null)
                              setRejectReason('')
                            }}
                          >
                            Cancel
                          </Button>
                          <Button
                            variant="danger"
                            size="sm"
                            loading={reviewingClaimId === claim.id}
                            disabled={!rejectReason.trim()}
                            onClick={() => void handleRejectClaim(claim.id)}
                          >
                            Confirm reject
                          </Button>
                        </div>
                      ) : (
                        <div key="actions" style={{ display: 'flex', gap: 'var(--space-2)' }}>
                          <Button
                            variant="primary"
                            size="sm"
                            loading={reviewingClaimId === claim.id}
                            onClick={() => void handleConfirmClaim(claim.id)}
                          >
                            Confirm
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => setRejectingClaimId(claim.id)}
                          >
                            Reject
                          </Button>
                        </div>
                      )
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
      </Card>
    </div>
  )
}
