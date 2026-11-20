import { type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../design/components'
import { ResultScreen } from '../../shell/ResultScreen'

export function PaymentFailed(): JSX.Element {
  const navigate = useNavigate()

  return (
    <ResultScreen
      tone="error"
      title="Payment unsuccessful"
      actions={
        <>
          <Button variant="secondary" onClick={() => navigate(-1)}>
            Try again
          </Button>
          <Button variant="primary" onClick={() => navigate('/my-billing')}>
            Back to billing
          </Button>
        </>
      }
    >
      Your payment could not be completed. No charge was made. Please try again or use manual bank transfer.
    </ResultScreen>
  )
}
