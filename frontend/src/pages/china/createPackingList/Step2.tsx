import { type JSX } from 'react'
import { Banner, Button } from '../../../design/components'
import { formatCbm } from '../../../lib/format'
import styles from '../CreatePackingList.module.css'
import type { PackingListForm } from './useCreatePackingListForm'
import { ItemsTable } from './ItemsTable'
import { ContextBar, PricingEstimate } from './Step2Parts'

/** Step 2: the cargo, one row per carton or batch, with CBM, weight and value. */
export function Step2({ form }: { form: PackingListForm }): JSX.Element {
  const {
    setStep,
    submitting,
    canProceedFrom2,
    requestSave,
    exceedsCapacity,
    totals,
    remainingCapacityCbm,
    otherUsedCbm,
    containerCapacity,
    selectedContainer,
  } = form
  return (
    <>
      <ContextBar form={form} />
      {exceedsCapacity && containerCapacity != null && remainingCapacityCbm != null && (
        <>
          <div className={styles.spacer} />
          <Banner variant="error" title="Exceeds container CBM capacity">
            Items total {formatCbm(totals.cbm)} CBM, which exceeds{' '}
            {selectedContainer?.container_number ?? 'this container'}&apos;s remaining capacity of{' '}
            {formatCbm(remainingCapacityCbm)} CBM ({formatCbm(otherUsedCbm)} /{' '}
            {formatCbm(containerCapacity)} CBM already used). Reduce item dimensions or quantity to
            fit within capacity.
          </Banner>
        </>
      )}
      <div className={styles.spacer} />
      <ItemsTable form={form} />

      <div className={styles.spacer} />
      <PricingEstimate form={form} />

      <div className={styles.actionsRow}>
        <Button variant="ghost" icon="arrowleft" onClick={() => setStep(1)}>
          Back: Details
        </Button>
        <div className={styles.actionsGroup}>
          <Button
            variant="secondary"
            loading={submitting}
            disabled={exceedsCapacity}
            onClick={() => void requestSave(false)}
          >
            Save draft
          </Button>
          <Button
            variant="primary"
            trailingIcon="arrowright"
            disabled={!canProceedFrom2}
            onClick={() => setStep(3)}
          >
            Next: Review
          </Button>
        </div>
      </div>
    </>
  )
}
