/**
 * DateField — a labelled date in the Field style (FD-11). The value is ISO (YYYY-MM-DD). The control is the
 * browser's date input (keyboard entry and the phone's own picker both work), drawn with the Field's border, height
 * and focus ring, and the chosen date is repeated in words under it ("Thu 13 Nov 2026"), so the day/month order is
 * never in doubt.
 */
import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { formatDate } from '../../lib/format'
import styles from './Field.module.css'
import { FieldShell } from './FieldShell'
import { Icon } from './Icon'

export interface DateFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'size'> {
  label: string
  hideLabel?: boolean
  optional?: boolean
  error?: string
  helper?: ReactNode
  value: string
}

export const DateField = forwardRef<HTMLInputElement, DateFieldProps>(function DateField(
  { label, hideLabel, optional, error, helper, value, id, disabled, className, ...rest },
  ref,
) {
  const inWords = value ? formatDate(value, 'long') : null
  return (
    <FieldShell
      label={label}
      hideLabel={hideLabel}
      optional={optional}
      error={error}
      helper={helper ?? (inWords && !hideLabel ? inWords : undefined)}
      id={id ?? rest.name}
      className={className}
    >
      {({ id: controlId, describedBy, invalid }) => (
        <div className={[styles.wrapper, error ? styles.wrapperError : '', disabled ? styles.wrapperDisabled : ''].filter(Boolean).join(' ')}>
          <Icon name="calendar" size={16} color="var(--color-ink-4)" />
          <input
            ref={ref}
            id={controlId}
            type="date"
            value={value}
            disabled={disabled}
            aria-describedby={describedBy}
            aria-invalid={invalid || undefined}
            className={styles.input}
            {...rest}
          />
        </div>
      )}
    </FieldShell>
  )
})
