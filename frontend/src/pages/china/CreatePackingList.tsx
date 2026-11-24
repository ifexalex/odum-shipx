import { type JSX } from 'react'
import { BULK_CONFIRM_THRESHOLD } from '../../api/packingList'
import { Banner, Button, Card, Modal, LinesSkeleton } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { UnsavedChangesGuard } from '../../shell/UnsavedChangesGuard'
import styles from './CreatePackingList.module.css'
import { CREATE_CONTAINER_FOR_PACKING_LIST } from './createPackingList/Step1'
import { WizardSteps } from './createPackingList/WizardSteps'
import { Step1 } from './createPackingList/Step1'
import { Step2 } from './createPackingList/Step2'
import { Step3 } from './createPackingList/Step3'
import { useCreatePackingListForm } from './createPackingList/useCreatePackingListForm'
import { formatCbm, formatKg, formatTime } from '../../lib/format'

export function CreatePackingList(): JSX.Element {
  const form = useCreatePackingListForm()
  const { isEdit, step, pendingSave, setPendingSave, submitting, editReady, error, totals, bulkLines, handleSave } = form
  const { tabDraft, hasUnsavedInput, restoredDraft, setRestoredDraft, startOver } = form

  return (
    <div className={styles.wrap}>
      {/* Ask before leaving with unsaved input (FD-54). A new list's input is kept in the tab, so leaving loses nothing
          until the tab closes; creating the container it needs is a round trip, not a departure. */}
      <UnsavedChangesGuard
        when={hasUnsavedInput && !submitting}
        allow={(pathname) => pathname === CREATE_CONTAINER_FOR_PACKING_LIST.split('?')[0]}
        title="Leave this packing list?"
        undo={isEdit ? false : 'It stays in this tab, so you can come back and finish it.'}
      >
        {isEdit
          ? 'Your changes to this draft have not been saved.'
          : 'It has not been saved to ShipX yet. Save a draft to keep it for good.'}
      </UnsavedChangesGuard>
      <PageHeader
        title={isEdit ? 'Edit draft packing list' : 'Create packing list'}
        meta="Capture carton-level details for a customer's cargo. Submit for approval when complete."
        // Says the input is safe while the list is not yet saved to the server (FD-25).
        status={
          tabDraft.savedAt && (
            <span className={styles.draftSaved} role="status">
              Draft saved in this tab · {formatTime(tabDraft.savedAt)}
            </span>
          )
        }
      />

      {restoredDraft && (
        <div className={styles.banner}>
          <Banner
            variant="info"
            title="Picked up where you left off"
            dismissible
            onDismiss={() => setRestoredDraft(false)}
            action={
              <Button variant="ghost" size="sm" onClick={startOver}>
                Start over
              </Button>
            }
          >
            This packing list was not saved yet, so this tab kept what you had entered.
          </Banner>
        </div>
      )}

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
                  {item.weight_actual_kg != null && `, ${formatKg(item.weight_actual_kg)} kg each`}
                </>
              )}
            </li>
          ))}
        </ul>
        <p>
          Totals for this packing list: <strong>{totals.cartons}</strong> packages,{' '}
          <strong>{formatCbm(totals.cbm)} CBM</strong>, <strong>{formatKg(totals.weight)} kg</strong>.
        </p>
        <Banner variant="warning">
          Only use a quantity when the packages are genuinely identical. CBM drives billing, so one wrong
          dimension is repeated across every package in the batch.
        </Banner>
      </Modal>
    </div>
  )
}
