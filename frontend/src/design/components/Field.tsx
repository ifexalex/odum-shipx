/**
 * Field — a labelled text input or textarea (FD-11). Part of the Field family with Select, DateField, ColorField,
 * CellInput, RadioGroup and FileInput: pages use these, never a raw <input>, <select> or <textarea>.
 *
 * `label` is required (FD-50); `hideLabel` keeps it for screen readers when the design has no room. Required fields
 * carry no asterisk; mark the optional ones with `optional`.
 */
import { forwardRef, type InputHTMLAttributes, type ReactNode, type Ref, type TextareaHTMLAttributes } from 'react'
import styles from './Field.module.css'
import { FieldShell } from './FieldShell'
import { Icon, type IconName } from './Icon'

export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'type' | 'prefix' | 'suffix'> {
  label: string
  hideLabel?: boolean
  type?: string
  icon?: IconName
  trailing?: ReactNode
  error?: string
  helper?: ReactNode
  multiline?: boolean
  optional?: boolean
  rows?: number
  prefix?: ReactNode
  suffix?: ReactNode
}

// Forwards a ref and spreads native input attributes directly so it wires
// straight into react-hook-form's register()/Controller without a
// wrapper-around-a-wrapper: <Field label="Email" {...register('email')} error={errors.email?.message} />
export const Field = forwardRef<HTMLInputElement | HTMLTextAreaElement, FieldProps>(function Field(
  {
    label,
    hideLabel,
    type = 'text',
    icon,
    trailing,
    error,
    helper,
    multiline = false,
    optional = false,
    required = false,
    rows,
    prefix,
    suffix,
    id,
    disabled,
    className,
    ...rest
  },
  ref,
) {
  return (
    <FieldShell label={label} hideLabel={hideLabel} optional={optional} error={error} helper={helper} id={id ?? rest.name} className={className}>
      {({ id: controlId, describedBy, invalid }) => (
        <div
          className={[styles.wrapper, multiline ? styles.multiline : '', error ? styles.wrapperError : '', disabled ? styles.wrapperDisabled : '']
            .filter(Boolean)
            .join(' ')}
        >
          {icon && <Icon name={icon} size={16} color="var(--color-ink-4)" />}
          {prefix && <span className={styles.prefix}>{prefix}</span>}
          {multiline ? (
            <textarea
              id={controlId}
              ref={ref as Ref<HTMLTextAreaElement>}
              rows={rows}
              required={required}
              disabled={disabled}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              className={styles.textarea}
              // The common subset of attributes (value/onChange/onBlur/name/placeholder/...) is identical between input
              // and textarea; only `type` (excluded above) and a few input-only attributes diverge.
              {...(rest as unknown as TextareaHTMLAttributes<HTMLTextAreaElement>)}
            />
          ) : (
            <input
              id={controlId}
              ref={ref as Ref<HTMLInputElement>}
              type={type}
              required={required}
              disabled={disabled}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              className={styles.input}
              {...rest}
            />
          )}
          {suffix && <span className={styles.suffix}>{suffix}</span>}
          {trailing}
        </div>
      )}
    </FieldShell>
  )
})
