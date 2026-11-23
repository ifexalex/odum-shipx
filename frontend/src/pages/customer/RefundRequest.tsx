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
import { bankDetailsProblem } from '../../api/refundsRules'
import { Banner, Button, Card, Field, Kvp, Mono, RadioGroup } from '../../design/components'
import { formatNgn } from '../../lib/format'
import { PageHeader } from '../../shell/PageHeader'
import { UnsavedChangesGuard } from '../../shell/UnsavedChangesGuard'
import styles from './customer.module.css'
import { useInvoiceCrumb } from './useInvoiceCrumb'
import { toast } from '../../design/toast'

export function RefundRequest(): JSX.Element {
  const { id: billingId } = useParams<{ id: string }>()
  const billing = useInvoiceCrumb(billingId)
  const navigate = useNavigate()
  const idempotencyKey = useRef(crypto.randomUUID())

  const [amountNgn, setAmountNgn] = useState('')
  const [reason, setReason] = useState('')
  const [choice, setChoice] = useState<'immediate_refund' | 'credit_next_shipment'>('immediate_refund')
  // Where a bank refund is paid. PII: never logged; stored encrypted server-side.
  const [bankName, setBankName] = useState('')
  const [accountNumber, setAccountNumber] = useState('')
  const [accountName, setAccountName] = useState('')
  const [showBankProblem, setShowBankProblem] = useState(false)
  const toBank = choice === 'immediate_refund'
  const bankProblem = toBank ? bankDetailsProblem({ bankName, accountNumber, accountName }) : null
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty =
    amountNgn !== '' || reason.trim() !== '' || bankName.trim() !== '' || accountNumber !== '' || accountName.trim() !== ''
  const ACCOUNT_NUMBER_MESSAGE = 'Enter your 10-digit account number.'
  const accountNumberInlineError =
    toBank && ((accountNumber.length > 0 && accountNumber.length !== 10) || (showBankProblem && bankProblem === ACCOUNT_NUMBER_MESSAGE))
      ? ACCOUNT_NUMBER_MESSAGE
      : undefined
  const overpayment =
    billing && billing.total_paid_ngn != null && billing.total_due_ngn != null
      ? Math.max(0, Number(billing.total_paid_ngn) - Number(billing.total_due_ngn))
      : 0

  async function handleSubmit(): Promise<void> {
    if (!billingId) return
    if (bankProblem) {
      setShowBankProblem(true)
      return
    }
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
        ...(toBank
          ? { bank_name: bankName.trim(), account_number: accountNumber.trim(), account_name: accountName.trim() }
          : {}),
      }
      await refundsApi.create(body, idempotencyKey.current)
      toast.success('Refund request sent', 'Our accounts team will review it.')
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
      <UnsavedChangesGuard when={dirty && !submitting}>Your refund request has not been submitted yet.</UnsavedChangesGuard>
      <PageHeader
        title="Request a refund"
        meta="Submit a refund request for review by our accounts team."
      />

      {billing && (
        <div className={styles.contextCard}>
          <Card padding="default">
            <Kvp label="Invoice" value={<Mono>{billing.invoice_number ?? billingId}</Mono>} />
            {billing.container_number && <Kvp label="Container" value={<Mono>{billing.container_number}</Mono>} />}
            {billing.total_due_ngn != null && <Kvp label="Total billed" value={<Mono>{formatNgn(billing.total_due_ngn)}</Mono>} />}
            {billing.total_paid_ngn != null && (
              <Kvp label="Amount paid" value={<Mono>{formatNgn(billing.total_paid_ngn)}</Mono>} divider={overpayment > 0} />
            )}
            {overpayment > 0 && (
              <>
                <Kvp
                  label="Overpayment balance"
                  value={<Mono color="var(--color-primary)">{formatNgn(overpayment)}</Mono>}
                  divider={false}
                />
                <div className={styles.contextAction}>
                  <Button variant="secondary" size="sm" onClick={() => setAmountNgn(String(overpayment))}>
                    Use full overpayment
                  </Button>
                </div>
              </>
            )}
          </Card>
        </div>
      )}

      <form
        className={styles.formCard}
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) void handleSubmit()
        }}
      >
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

        <RadioGroup
          label="Refund preference"
          name="refund_choice"
          value={choice}
          onChange={setChoice}
          options={[
            { value: 'immediate_refund', label: 'Bank account refund', hint: 'Refunded to your bank account within 5–7 business days.' },
            {
              value: 'credit_next_shipment',
              label: 'Credit on next shipment',
              hint: 'Applied automatically to your next container billing; anything left over stays as credit for the one after.',
            },
          ]}
        />

        {toBank && (
          <div>
            <Field
              label="Bank"
              name="bank_name"
              required
              autoComplete="off"
              placeholder="e.g. Zenith Bank"
              value={bankName}
              onChange={(e) => setBankName(e.target.value)}
            />
            <Field
              label="Account number"
              name="account_number"
              required
              inputMode="numeric"
              maxLength={10}
              autoComplete="off"
              placeholder="10 digits"
              value={accountNumber}
              onChange={(e) => setAccountNumber(e.target.value.replace(/\D/g, ''))}
              error={accountNumberInlineError}
            />
            <Field
              label="Account name"
              name="account_name"
              required
              autoComplete="off"
              placeholder="As it appears on the account"
              value={accountName}
              onChange={(e) => setAccountName(e.target.value)}
            />
            {showBankProblem && bankProblem && bankProblem !== accountNumberInlineError && (
              <Banner variant="error">{bankProblem}</Banner>
            )}
          </div>
        )}

        <div className={styles.formActions}>
          <Button variant="ghost" onClick={() => navigate(-1)} disabled={submitting}>Cancel</Button>
          <Button type="submit" variant="primary" loading={submitting} disabled={!canSubmit}>
            Submit request
          </Button>
        </div>
      </form>
    </div>
  )
}
