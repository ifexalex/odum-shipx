/**
 * Customer refund request form for /my-billing/:id/refund-request.
 *
 * Security: account_number and account_name are PII — never log them.
 * They are sent over HTTPS and stored encrypted server-side (shared/encryption.py).
 */

import { useRef, useState, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { refundsApi, type CreateRefundInput } from '../../api/refunds'
import { Banner, Button, Field } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'

export function RefundRequest(): JSX.Element {
  const { id: billingId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const idempotencyKey = useRef(crypto.randomUUID())

  const [amountNgn, setAmountNgn] = useState('')
  const [reason, setReason] = useState('')
  const [choice, setChoice] = useState<'immediate_refund' | 'credit_next_shipment'>('immediate_refund')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    if (!billingId) return
    setSubmitting(true)
    setError(null)
    try {
      const body: CreateRefundInput = {
        customer_id: '',  // Server derives from JWT for customer role
        billing_id: billingId,
        refund_type: 'overpayment',
        amount_requested_ngn: amountNgn,
        customer_choice: choice,
        notes: reason || undefined,
      }
      await refundsApi.create(body, idempotencyKey.current)
      navigate(`/my-billing/${billingId}`, { state: { refundFiled: true } })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not submit refund request.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = Number(amountNgn) > 0 && !submitting

  return (
    <div className={styles.page}>
      <PageHeader title="Request a Refund" subtitle="Submit a refund request for review by our accounts team." />

      <div className={styles.formCard}>
        {error && (
          <div className={styles.banner}>
            <Banner variant="error" title="Submission failed">{error}</Banner>
          </div>
        )}

        <Field
          label="Amount requested (₦)"
          name="amount_ngn"
          required
          type="number"
          placeholder="e.g. 25000"
          value={amountNgn}
          onChange={(e) => setAmountNgn(e.target.value)}
        />

        <Field
          label="Reason for refund"
          name="reason"
          multiline
          optional
          placeholder="Briefly explain why you are requesting a refund…"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />

        <div>
          <label style={{ display: 'block', fontWeight: 600, fontSize: '0.875rem', marginBottom: 8 }}>
            Refund preference
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer', fontSize: '0.875rem' }}>
              <input
                type="radio"
                checked={choice === 'immediate_refund'}
                onChange={() => setChoice('immediate_refund')}
                style={{ marginTop: 2 }}
              />
              <div>
                <strong>Bank account refund</strong>
                <p style={{ margin: 0, color: 'var(--color-text-muted)' }}>
                  Refunded to your bank account within 5–7 business days.
                </p>
              </div>
            </label>
            <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer', fontSize: '0.875rem' }}>
              <input
                type="radio"
                checked={choice === 'credit_next_shipment'}
                onChange={() => setChoice('credit_next_shipment')}
                style={{ marginTop: 2 }}
              />
              <div>
                <strong>Credit on next shipment</strong>
                <p style={{ margin: 0, color: 'var(--color-text-muted)' }}>
                  Applied automatically to your next container billing; anything left over stays as credit for the one
                  after.
                </p>
              </div>
            </label>
          </div>
        </div>

        <div className={styles.formActions}>
          <Button variant="ghost" onClick={() => navigate(-1)} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Submit request
          </Button>
        </div>
      </div>
    </div>
  )
}
