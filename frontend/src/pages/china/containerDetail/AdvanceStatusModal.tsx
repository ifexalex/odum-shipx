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
import { Banner, Button, Field, Modal, Mono, DateField } from '../../../design/components'
import styles from '../ContainerDetail.module.css'
import { statusLabel } from '../../../design/status'
import { toast } from '../../../design/toast'

export interface AdvanceModalProps {
  container: Container
  target: ContainerStatus
  /** Distinct customers with cargo on this container (from its packing lists). */
  customerCount: number
  /** Approved packing lists currently on this container (used to warn before sealing empty). */
  approvedCount?: number
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
  approvedCount,
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
  const sealingWithoutApproved = target === 'sealed' && approvedCount === 0

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
    <Modal
      open
      onClose={onClose}
      title={
        step === 'form'
          ? `Advance to ${statusLabel('container', target)}`
          : `Confirm — ${statusLabel('container', target)}`
      }
      size="sm"
      footer={
        step === 'form' ? (
          <>
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
          </>
        ) : (
          <>
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
          </>
        )
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error">{error}</Banner>}

        {step === 'form' && (
          <>
            {sealingWithoutApproved && (
              <Banner variant="warning" title="No approved packing lists yet">
                Approve at least one packing list on this container before sealing — otherwise the
                server will refuse sealing or generate an empty manifest.
              </Banner>
            )}
            {requirementHint && <Banner variant="info">{requirementHint}</Banner>}
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
          </>
        )}
      </div>
    </Modal>
  )
}
