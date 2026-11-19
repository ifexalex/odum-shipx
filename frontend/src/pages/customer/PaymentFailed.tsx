import { type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../design/components'
import styles from './customer.module.css'

export function PaymentFailed(): JSX.Element {
  const navigate = useNavigate()

  return (
    <div className={styles.resultPage}>
      <div className={styles.resultIcon} style={{ color: 'var(--color-error)' }}>✗</div>
      <h1 className={styles.resultTitle}>Payment unsuccessful</h1>
      <p className={styles.resultBody}>
        Your payment could not be completed. No charge was made. Please try again or use manual bank transfer.
      </p>
      <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
        <Button variant="secondary" onClick={() => navigate(-1)}>
          Try again
        </Button>
        <Button variant="primary" onClick={() => navigate('/my-billing')}>
          Back to billing
        </Button>
      </div>
    </div>
  )
}
