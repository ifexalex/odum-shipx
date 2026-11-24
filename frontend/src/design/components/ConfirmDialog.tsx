/**
 * ConfirmDialog (FD-24): the one confirmation before a destructive action (cancel, delete, deactivate, reject, waive,
 * withdraw). It names the record, says what will happen and whether it can be undone, and commits with a danger
 * button, never a brand-green one. An irreversible action asks the user to type the record's reference first, as the
 * customer erasure already did.
 *
 *   <ConfirmDialog
 *     open={deleting}
 *     title="Delete container MSCU1234567?"
 *     confirmLabel="Delete container"
 *     undo={false}
 *     typeToConfirm="MSCU1234567"
 *     onConfirm={handleDelete}
 *     onCancel={() => setDeleting(false)}
 *   >
 *     It has no packing lists and will be removed.
 *   </ConfirmDialog>
 */
import { useState, type JSX, type ReactNode } from 'react'
import { Banner } from './Banner'
import { Button } from './Button'
import { Field } from './Field'
import { Modal } from './Modal'
import styles from './ConfirmDialog.module.css'

export interface ConfirmDialogProps {
  open: boolean
  /** A question naming the record: "Cancel container MSCU1234567?". */
  title: string
  /** What will happen, in a sentence or two. */
  children: ReactNode
  /** The commit button, naming the action: "Cancel container". */
  confirmLabel: string
  /** The button that backs out; "Keep it" unless the action reads better with another ("Keep editing"). */
  cancelLabel?: string
  /** How to undo it ("You can reactivate it later."), or false when it cannot be undone. */
  undo: string | false
  /** For an irreversible action: the reference the user must type before the button works. */
  typeToConfirm?: string
  /** A failure to show inside the dialog. */
  error?: string | null
  busy?: boolean
  onConfirm: () => void | Promise<void>
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = 'Keep it',
  undo,
  typeToConfirm,
  error,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): JSX.Element | null {
  const [typed, setTyped] = useState('')
  if (!open) return null
  const matches = !typeToConfirm || typed.trim() === typeToConfirm
  const cancel = (): void => {
    setTyped('')
    onCancel()
  }
  return (
    <Modal
      open
      onClose={busy ? undefined : cancel}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={cancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant="danger" loading={busy} disabled={!matches} onClick={() => void onConfirm()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className={styles.body}>
        <p className={styles.text}>{children}</p>
        <p className={undo ? styles.undo : styles.final}>{undo || 'This cannot be undone.'}</p>
        {typeToConfirm && (
          <Field
            label={`Type ${typeToConfirm} to confirm`}
            name="confirm_reference"
            autoComplete="off"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        )}
        {error && (
          <Banner variant="error" title="That did not work">
            {error}
          </Banner>
        )}
      </div>
    </Modal>
  )
}
