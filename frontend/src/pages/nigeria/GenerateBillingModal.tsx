import { useQuery } from '@tanstack/react-query'
import { useMemo, useState, type JSX } from 'react'
import { billingApi, type InvoiceResult } from '../../api/billing'
import { groupUnbilledByContainer } from '../../api/billingRules'
import { ApiError } from '../../api/client'
import { formatCbm } from '../../api/decimal'
import { billingKeys } from '../../api/keys'
import { Banner, Button, Modal, Mono, Select } from '../../design/components'
import { STALE_30S } from '../../lib/queryClient'
import { InvoiceOutcomeBanner } from '../china/InvoiceOutcomeBanner'
import styles from './GenerateBillingModal.module.css'

interface Outcome {
  containerId: string
  results: InvoiceResult[]
}

export interface GenerateBillingModalProps {
  onClose: () => void
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

/**
 * Pick a cleared container and invoice everyone on it who has not been invoiced.
 *
 * Clearing a container invoices its customers automatically, so this is the manual path
 * for the ones that were skipped (rates not set yet, no CBM) or failed. Only containers
 * that still have a customer to invoice are offered, because invoicing is idempotent and
 * there is nothing to do for the rest. Mount it only while open, so each opening starts
 * from a clean picker.
 */
export function GenerateBillingModal({ onClose }: GenerateBillingModalProps): JSX.Element {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  const unbilledQ = useQuery({
    queryKey: billingKeys.unbilled(),
    queryFn: () => billingApi.unbilled(),
    staleTime: STALE_30S,
  })
  const containers = useMemo(() => groupUnbilledByContainer(unbilledQ.data ?? []), [unbilledQ.data])

  // With a single candidate there is nothing to choose, so it is selected for them.
  const onlyContainer = containers.length === 1 ? containers[0] : undefined
  const activeId = selectedId ?? onlyContainer?.containerId ?? null
  const active = containers.find((c) => c.containerId === activeId) ?? null

  async function generate(): Promise<void> {
    if (active === null) return
    setBusy(true)
    setError(null)
    try {
      // A successful POST /v1/billing refreshes every billing query, the invoice list included.
      const response = await billingApi.generateForContainer(active.containerId)
      setOutcome({ containerId: active.containerId, results: response.results })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not generate the invoices.')
    } finally {
      setBusy(false)
    }
  }

  if (outcome !== null) {
    return (
      <Modal
        open
        onClose={onClose}
        title="Generate billing"
        footer={<Button variant="primary" mutates={false} onClick={onClose}>Done</Button>}
      >
        {outcome.results.length === 0 ? (
          <Banner variant="info" title="Nothing to invoice">
            No customer on this container needed an invoice.
          </Banner>
        ) : (
          <InvoiceOutcomeBanner
            containerId={outcome.containerId}
            results={outcome.results}
            canGenerate
            onResults={(results) => setOutcome({ containerId: outcome.containerId, results })}
          />
        )}
      </Modal>
    )
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Generate billing"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={active === null} onClick={() => void generate()}>
            Generate invoices
          </Button>
        </>
      }
    >
      {unbilledQ.isError ? (
        <Banner variant="error" title="Couldn't load containers">
          {unbilledQ.error instanceof ApiError ? unbilledQ.error.message : 'Try again in a moment.'}
        </Banner>
      ) : unbilledQ.isPending ? (
        <p className={styles.muted}>Loading containers…</p>
      ) : containers.length === 0 ? (
        <Banner variant="success" title="Nothing to invoice">
          Every customer on a cleared container already has an invoice. Containers are invoiced when they are
          cleared; anyone skipped at that point, for example because rates were not set, shows up here.
        </Banner>
      ) : (
        <div className={styles.body}>
          <p className={styles.intro}>
            Choose a cleared container. Each customer on it who has cargo to bill and no invoice gets one.
            Customers who already have an invoice are left alone.
          </p>
          {error && (
            <Banner variant="error" title="Could not generate">
              {error}
            </Banner>
          )}
          <div className={styles.field}>
            {/* A native select, not the searchable Combobox: the modal body scrolls, which clips
                the Combobox's dropdown. The list is short by nature — only containers that still
                have a customer to invoice. */}
            <Select label="Container"
              id="generate_billing_container"
              value={activeId ?? ''}
              onChange={(e) => setSelectedId(e.target.value || null)}
            >
              {activeId === null && <option value="">Select a container…</option>}
              {containers.map((c) => (
                <option key={c.containerId} value={c.containerId}>
                  {c.containerNumber} — {plural(c.customers.length, 'customer')} · {formatCbm(c.totalCbm)} CBM
                </option>
              ))}
            </Select>
          </div>
          {active && (
            <ul className={styles.customers} aria-label={`Customers on ${active.containerNumber} without an invoice`}>
              {active.customers.map((customer) => (
                <li key={customer.id} className={styles.customer}>
                  <span>{customer.name}</span>
                  <Mono color="var(--color-ink-3)">{formatCbm(customer.cbm)} CBM</Mono>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Modal>
  )
}
