/**
 * FieldShell — the parts every control in the Field family shares (FD-11, FD-50): a label that is always there
 * (visually hidden when the design has no room, never missing), the "Optional" tag, and the error or helper text,
 * all wired to the control with `htmlFor` and `aria-describedby`.
 *
 * Required fields carry no asterisk: forms mark the optional ones only.
 */
import { useId, type JSX, type ReactNode } from 'react'
import styles from './Field.module.css'
import { Icon } from './Icon'

export interface FieldShellProps {
  /** The control's name, shown above it. Required: a control with no name cannot be found by a screen reader. */
  label: string
  /** Keep the label for assistive technology but do not show it (a search box with an icon, a table cell). */
  hideLabel?: boolean
  optional?: boolean
  error?: string
  helper?: ReactNode
  /** The control's id; one is made if absent. */
  id?: string
  className?: string
  /** Renders the control, given the ids to wire it with. */
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode
}

export function FieldShell({ label, hideLabel, optional, error, helper, id, className, children }: FieldShellProps): JSX.Element {
  const generated = useId()
  const controlId = id ?? `field-${generated}`
  const messageId = `${controlId}-message`
  const optionalId = `${controlId}-optional`
  const hasMessage = Boolean(error || helper)
  // "Optional" is read as part of the description, not the name: the field is "Brand colour", not "Brand colour Optional".
  const describedBy = [optional ? optionalId : '', hasMessage ? messageId : ''].filter(Boolean).join(' ') || undefined
  return (
    <div className={[styles.fieldRoot, className].filter(Boolean).join(' ')}>
      <label className={hideLabel ? styles.visuallyHidden : styles.label} htmlFor={controlId}>
        <span>{label}</span>
        {optional && !hideLabel && (
          <span className={styles.optionalTag} aria-hidden="true">
            Optional
          </span>
        )}
      </label>
      {optional && (
        <span id={optionalId} className={styles.visuallyHidden}>
          Optional
        </span>
      )}
      {children({ id: controlId, describedBy, invalid: Boolean(error) })}
      {error ? (
        <div id={messageId} className={styles.errorMsg}>
          <Icon name="alert" size={12} color="var(--color-error)" />
          {error}
        </div>
      ) : (
        helper && (
          <div id={messageId} className={styles.helper}>
            {helper}
          </div>
        )
      )}
    </div>
  )
}
