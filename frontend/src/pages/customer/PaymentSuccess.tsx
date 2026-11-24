import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type JSX } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { billingApi } from '../../api/billing'
import { billingKeys } from '../../api/keys'
import { ApiError } from '../../api/client'
import { Button } from '../../design/components'
import { runDocument } from '../../lib/documents'
import styles from './customer.module.css'
import { useInvoiceCrumb } from './useInvoiceCrumb'
import { ResultScreen } from '../../shell/ResultScreen'

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
  // The payment this page confirmed, for its receipt (FD-43): found on the invoice by its Paystack reference, read once
  // the payment is confirmed (its own cache slot, so a copy read before the payment cannot answer). A receipt is a
  // bonus here: not finding one leaves the page as it was.
  const { data: confirmedInvoice } = useQuery({
    queryKey: [...billingKeys.detail(id ?? ''), 'after-payment', reference],
    queryFn: () => billingApi.get(id!),
    enabled: state === 'success' && !!id,
  })
  const receiptPaymentId = confirmedInvoice?.payments?.find((p) => p.payment_reference === reference)?.id ?? null
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
      <ResultScreen
        tone="success"
        title="Payment successful"
        actions={
          <>
            {receiptPaymentId && (
              <Button
                variant="secondary"
                icon="download"
                onClick={() => void runDocument('your receipt', () => billingApi.receiptPdf(receiptPaymentId))}
              >
                Download receipt
              </Button>
            )}
            <Button variant="secondary" onClick={() => navigate(`/my-billing/${id}`)}>
              View invoice
            </Button>
            <Button variant="primary" onClick={() => navigate('/my-billing')}>
              Back to billing
            </Button>
          </>
        }
      >
        Your payment has been confirmed and your billing record is updated. Your release note is issued once the
        balance is fully settled.
      </ResultScreen>
    )
  }

  if (state === 'pending') {
    return (
      <ResultScreen
        tone="warning"
        title="Payment not yet confirmed"
        actions={
          <>
            <Button variant="secondary" onClick={() => navigate(`/my-billing/${id}`)}>
              View invoice
            </Button>
            <Button variant="primary" onClick={() => navigate('/my-billing')}>
              Back to billing
            </Button>
          </>
        }
      >
        Paystack hasn't confirmed this payment as successful yet. If you completed the payment, check back on your
        invoice in a moment — otherwise no charge was made and you can try again.
      </ResultScreen>
    )
  }

  return (
    <ResultScreen
      tone="error"
      title="Couldn't confirm your payment automatically"
      actions={
        <>
          <Button variant="secondary" onClick={() => navigate(`/my-billing/${id}`)}>
            View invoice
          </Button>
          <Button variant="primary" onClick={() => navigate('/my-billing')}>
            Back to billing
          </Button>
        </>
      }
    >
      {error} If you were charged, your invoice will update shortly — otherwise please try again or contact your
      shipping company.
    </ResultScreen>
  )
}
