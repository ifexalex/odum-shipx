import { useState, type JSX } from 'react'
import { ApiError } from '../../../api/client'
import {
  containerAdvanceRequirementHint,
} from '../../../api/containerRules'
import {
  containersApi,
  type Container,
  type ContainerStatus,
  type ContainerStatusUpdate,
} from '../../../api/tracking'
import { Banner, Button, Field, Mono, DialogGuard, DateField } from '../../../design/components'
import styles from '../ContainerDetail.module.css'
import { statusLabel } from '../../../design/status'
import { toast } from '../../../design/toast'

export interface AdvanceModalProps {
  container: Container
  target: ContainerStatus
  /** Distinct customers with cargo on this container (from its packing lists). */
  customerCount: number
  onClose: () => void
  onAdvanced: (updated: ContainerStatusUpdate) => void
}

/**
 * Customer-facing side effects per stage — mirrors services/tracking/service.py:
 * `at_warehouse` enqueues a container-arrived notification to every customer on
 * the container; `cleared` publishes PaymentDue per customer (billing +
 * payment-due notifications downstream). Every other stage is silent.
 */
function customerImpactFor(
  target: ContainerStatus,
  count: number,
): { variant: 'warning' | 'info'; text: string } | null {
  if (target === 'at_warehouse') {
    return {
      variant: 'warning',
      text: `${count} customer${count === 1 ? '' : 's'} on this container will be notified that their cargo has arrived, via their chosen channels (SMS · WhatsApp · Email).`,
    }
  }
  if (target === 'cleared') {
    return {
      variant: 'warning',
      text: `Billing will be generated for ${count} customer${count === 1 ? '' : 's'} on this container, and each will receive a payment-due notification.`,
    }
  }
  return null
}

// 6.4 / audit gap A5 — two-step flow: details form → confirmation that spells
// out the customer-facing side effects before anything is sent.
export function AdvanceStatusModal({
  container,
  target,
  customerCount,
  onClose,
  onAdvanced,
}: AdvanceModalProps): JSX.Element {
  const [step, setStep] = useState<'form' | 'confirm'>('form')
  const [shipDate, setShipDate] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requirementHint = containerAdvanceRequirementHint(target)
  const requiresShipDate = target === 'in_transit'
  const impact = customerImpactFor(target, customerCount)

  async function handleConfirm(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const updated = await containersApi.updateStatus(container.id, {
        new_status: target,
        ship_date: shipDate || undefined,
        notes: notes || undefined,
      })
      toast.success(`Container moved to ${statusLabel('container', updated.status)}`, updated.container_number)
      onAdvanced(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update the container status.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <DialogGuard onClose={onClose} />
      <div
        className={styles.modalPanel}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>
          {step === 'form'
            ? `Advance to ${statusLabel('container', target)}`
            : `Confirm — ${statusLabel('container', target)}`}
        </h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error">{error}</Banner>
          </div>
        )}

        {step === 'form' && (
          <>
            {requirementHint && (
              <div className={styles.modalBanner}>
                <Banner variant="info">{requirementHint}</Banner>
              </div>
            )}
            {requiresShipDate && (
              <DateField
                label="Ship date"
                name="shipDate"
                required
                value={shipDate}
                onChange={(event) => setShipDate(event.target.value)}
              />
            )}
            <Field
              label="Notes"
              name="advanceNotes"
              optional
              multiline
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                trailingIcon="arrowright"
                disabled={requiresShipDate && !shipDate}
                onClick={() => setStep('confirm')}
              >
                Continue
              </Button>
            </div>
          </>
        )}

        {step === 'confirm' && (
          <>
            <div className={styles.advanceSummary}>
              <Mono>{container.container_number}</Mono>
              <span className={styles.advanceSummaryArrow}>
                {statusLabel('container', container.status)} →{' '}
                <strong>{statusLabel('container', target)}</strong>
              </span>
              {shipDate && <span className={styles.advanceSummaryMeta}>Ship date: {shipDate}</span>}
            </div>
            <div className={styles.modalBanner}>
              {impact ? (
                <Banner variant={impact.variant} icon="bell" title="Customers will be contacted">
                  {impact.text}
                </Banner>
              ) : (
                <Banner variant="info">
                  No customer notifications are sent at this stage — customers see the updated
                  tracking status only.
                </Banner>
              )}
            </div>
            <div className={styles.modalActions}>
              <Button
                variant="ghost"
                icon="arrowleft"
                onClick={() => setStep('form')}
                disabled={submitting}
              >
                Back
              </Button>
              <Button
                variant="primary"
                icon="check"
                loading={submitting}
                onClick={() => void handleConfirm()}
              >
                {impact ? 'Confirm & notify' : 'Confirm'}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
