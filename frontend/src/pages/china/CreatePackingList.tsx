import { type JSX } from 'react'
import { BULK_CONFIRM_THRESHOLD } from '../../api/packingList'
import { Banner, Button, Card, Modal, LinesSkeleton } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import styles from './CreatePackingList.module.css'
import { WizardSteps } from './createPackingList/WizardSteps'
import { Step1 } from './createPackingList/Step1'
import { Step2 } from './createPackingList/Step2'
import { Step3 } from './createPackingList/Step3'
import { useCreatePackingListForm } from './createPackingList/useCreatePackingListForm'

export function CreatePackingList(): JSX.Element {
  const form = useCreatePackingListForm()
  const { isEdit, step, pendingSave, setPendingSave, submitting, editReady, error, totals, bulkLines, handleSave } = form

  return (
    <div className={styles.wrap}>
      <PageHeader
        title={isEdit ? 'Edit draft packing list' : 'Create packing list'}
        meta="Capture carton-level details for a customer's cargo. Submit for approval when complete."
      />

      {!editReady ? (
        <Card padding="large">
          <LinesSkeleton label="Loading draft" />
        </Card>
      ) : (
      <>
      <WizardSteps current={step} />
      <div className={styles.spacer} />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't save">{error}</Banner>
        </div>
      )}

      {step === 1 && <Step1 form={form} />}

      {step === 2 && <Step2 form={form} />}

      {step === 3 && <Step3 form={form} />}

      </>
      )}

      <Modal
        open={pendingSave !== null}
        onClose={() => setPendingSave(null)}
        title={`Create ${totals.cartons} packages?`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingSave(null)}>
              Go back
            </Button>
            <Button
              variant="primary"
              icon="check"
              loading={submitting}
              onClick={() => void handleSave(pendingSave?.submitForApproval ?? false)}
            >
              Yes, create them
            </Button>
          </>
        }
      >
        <p>
          {bulkLines.length === 1 ? 'One line sets' : `${bulkLines.length} lines set`} a quantity of{' '}
          {BULK_CONFIRM_THRESHOLD} or more. Each package becomes its own line with its own tag, and is billed
          separately.
        </p>
        <ul>
          {bulkLines.map(({ item, index, qty }) => (
            <li key={index}>
              <strong>{qty}</strong> × {item.description || 'item'} ({item.package_unit ?? 'carton'})
              {item.length_cm != null && item.width_cm != null && item.height_cm != null && (
                <>
                  {' — '}
                  {item.length_cm}×{item.width_cm}×{item.height_cm} cm
                  {item.weight_actual_kg != null && `, ${item.weight_actual_kg} kg each`}
                </>
              )}
            </li>
          ))}
        </ul>
        <p>
          Totals for this packing list: <strong>{totals.cartons}</strong> packages,{' '}
          <strong>{totals.cbm.toFixed(2)} CBM</strong>, <strong>{totals.weight.toFixed(1)} kg</strong>.
        </p>
        <Banner variant="warning">
          Only use a quantity when the packages are genuinely identical. CBM drives billing, so one wrong
          dimension is repeated across every package in the batch.
        </Banner>
      </Modal>
    </div>
  )
}
