import { useEffect, useState, type JSX } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { billingApi } from '../../api/billing'
import { ApiError } from '../../api/client'
import { Button } from '../../design/components'
import styles from './customer.module.css'
import { useInvoiceCrumb } from './useInvoiceCrumb'

type ReconcileState = 'verifying' | 'success' | 'pending' | 'error'

// Ground-truth gap found live: this page used to unconditionally claim
// success and rely entirely on the gateway webhook to actually mark the
// bill paid ("being confirmed automatically"). Paystack's servers can never
// reach a local dev URL at all, and even in production a webhook can be
// delayed or lost — the customer saw Paystack's own "successful" page,
// clicked "View invoice", and found the bill still unpaid with "Pay" still
// live, offering to charge them again. This page now calls
// billingApi.verifyPayment() itself, using the `reference` Paystack appends
// to this exact URL, and shows what actually happened rather than a
// guaranteed-cheerful message. See services/payment_release/service.py's
// confirm_online_payment for the backend half.
export function PaymentSuccess(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  useInvoiceCrumb(id)
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  // Whether there is anything to verify is known from the URL at render time,
  // so it is the initial state rather than an effect that immediately corrects
  // itself — which rendered 'verifying' for a frame and cascaded a re-render.
  const reference = searchParams.get('reference') || searchParams.get('trxref')
  // Someone can land here without ever going through Paystack (direct link,
  // browser back/forward).
  const missingReference = !id || !reference
  const [state, setState] = useState<ReconcileState>(() => (missingReference ? 'error' : 'verifying'))
  const [error, setError] = useState<string | null>(() =>
    missingReference ? 'No payment reference found for this page.' : null,
  )

  useEffect(() => {
    if (!id || !reference) return
    void (async () => {
      try {
        const result = await billingApi.verifyPayment(id, reference)
        if (result.gateway_status === 'success') {
          setState('success')
        } else {
          setState('pending')
        }
      } catch (err) {
        setState('error')
        setError(err instanceof ApiError ? err.message : 'Could not confirm your payment automatically.')
      }
    })()
  }, [id, reference])

  if (state === 'verifying') {
    return (
      <div className={styles.resultPage}>
        <p className={styles.resultBody}>Confirming your payment…</p>
      </div>
    )
  }

  if (state === 'success') {
    return (
      <div className={styles.resultPage}>
        <div className={styles.resultIcon}>✓</div>
        <h1 className={styles.resultTitle}>Payment successful!</h1>
        <p className={styles.resultBody}>
          Your payment has been confirmed and your billing record is updated. Your release note is issued once the
          balance is fully settled.
        </p>
        <div style={{ display: 'flex', gap: 12 }}>
          <Button variant="secondary" onClick={() => navigate(`/my-billing/${id}`)}>
            View invoice
          </Button>
          <Button variant="primary" onClick={() => navigate('/my-billing')}>
            Back to billing
          </Button>
        </div>
      </div>
    )
  }

  if (state === 'pending') {
    return (
      <div className={styles.resultPage}>
        <div className={styles.resultIcon} style={{ color: 'var(--color-warning)' }}>!</div>
        <h1 className={styles.resultTitle}>Payment not yet confirmed</h1>
        <p className={styles.resultBody}>
          Paystack hasn't confirmed this payment as successful yet. If you completed the payment, check back on your
          invoice in a moment — otherwise no charge was made and you can try again.
        </p>
        <div style={{ display: 'flex', gap: 12 }}>
          <Button variant="secondary" onClick={() => navigate(`/my-billing/${id}`)}>
            View invoice
          </Button>
          <Button variant="primary" onClick={() => navigate('/my-billing')}>
            Back to billing
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.resultPage}>
      <div className={styles.resultIcon} style={{ color: 'var(--color-error)' }}>!</div>
      <h1 className={styles.resultTitle}>Couldn't confirm your payment automatically</h1>
      <p className={styles.resultBody}>
        {error} If you were charged, your invoice will update shortly — otherwise please try again or contact your
        shipping company.
      </p>
      <div style={{ display: 'flex', gap: 12 }}>
        <Button variant="secondary" onClick={() => navigate(`/my-billing/${id}`)}>
          View invoice
        </Button>
        <Button variant="primary" onClick={() => navigate('/my-billing')}>
          Back to billing
        </Button>
      </div>
    </div>
  )
}
