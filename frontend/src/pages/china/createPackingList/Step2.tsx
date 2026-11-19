import { type JSX } from 'react'
import { Button } from '../../../design/components'
import styles from '../CreatePackingList.module.css'
import type { PackingListForm } from './useCreatePackingListForm'
import { ItemsTable } from './ItemsTable'
import { ContextBar, PricingEstimate } from './Step2Parts'

/** Step 2: the cargo, one row per carton or batch, with CBM, weight and value. */
export function Step2({ form }: { form: PackingListForm }): JSX.Element {
  const { setStep, submitting, canProceedFrom2, requestSave } = form
  return (
    <>
      <ContextBar form={form} />
      <div className={styles.spacer} />
      <ItemsTable form={form} />

      <div className={styles.spacer} />
      <PricingEstimate form={form} />

      <div className={styles.actionsRow}>
        <Button variant="ghost" icon="arrowleft" onClick={() => setStep(1)}>
          Back: Details
        </Button>
        <div className={styles.actionsGroup}>
          <Button variant="secondary" loading={submitting} onClick={() => void requestSave(false)}>
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
