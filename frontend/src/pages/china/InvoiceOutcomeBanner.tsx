import { useState, type JSX } from 'react'
import { billingApi, type InvoiceResult } from '../../api/billing'
import { ApiError } from '../../api/client'
import { Banner, Button } from '../../design/components'
import styles from './InvoiceOutcomeBanner.module.css'

/** Plain-language reason for a customer who has no invoice. Keys are the backend rule ids. */
const REASON_TEXT: Record<string, string> = {
  RATE_CONFIG_MISSING: 'CBM rate or dollar rate is not set',
  NO_CBM: 'no CBM on their approved packing lists',
  RATE_UNAVAILABLE: 'no market dollar rate could be fetched',
  GENERATION_ERROR: 'the invoice could not be created',
}

function reasonFor(row: InvoiceResult): string {
  return (row.reason && REASON_TEXT[row.reason]) || row.detail || 'not invoiced'
}

export interface InvoiceOutcomeBannerProps {
  containerId: string
  /** Outcome of invoicing, from the clearing response or a previous retry. */
  results: InvoiceResult[]
  /** Whether the viewer may run invoice generation (Nigeria staff and tenant admins). */
  canGenerate: boolean
  onResults: (results: InvoiceResult[]) => void
}

/**
 * Shows who was invoiced when a container cleared, and who was not and why.
 *
 * Clearing a container invoices every customer on it. Until this existed a customer who
 * could not be invoiced (rates not set, no CBM, a transient failure) only produced a log
 * line, so they were never billed and nobody knew. A customer without an invoice is shown
 * here with the reason, and "Generate missing invoices" completes the rest. Safe to repeat.
 */
export function InvoiceOutcomeBanner({ containerId, results, canGenerate, onResults }: InvoiceOutcomeBannerProps): JSX.Element | null {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const unbilled = results.filter((r) => r.status === 'skipped' || r.status === 'failed')
  const created = results.filter((r) => r.status === 'created').length

  async function retry(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      const response = await billingApi.generateForContainer(containerId)
      onResults(response.results)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not generate the missing invoices.')
    } finally {
      setBusy(false)
    }
  }

  if (results.length === 0) return null

  if (unbilled.length === 0) {
    return (
      <Banner variant="success" title="Invoices issued">
        {created > 0
          ? `${created} customer${created === 1 ? '' : 's'} invoiced.`
          : 'Every customer on this container already has an invoice.'}
      </Banner>
    )
  }

  return (
    <Banner
      variant="warning"
      title={`${unbilled.length} customer${unbilled.length === 1 ? '' : 's'} not invoiced`}
      action={
        canGenerate ? (
          <Button variant="secondary" size="sm" loading={busy} onClick={() => void retry()}>
            Generate missing invoices
          </Button>
        ) : undefined
      }
    >
      <ul className={styles.list}>
        {unbilled.map((row) => (
          <li key={row.customer_id}>
            <strong>{row.customer_name ?? 'Customer'}</strong> — {reasonFor(row)}
          </li>
        ))}
      </ul>
      {error && <p className={styles.note}>{error}</p>}
      {!canGenerate && <p className={styles.note}>Ask your Nigeria office or admin to generate them.</p>}
    </Banner>
  )
}
