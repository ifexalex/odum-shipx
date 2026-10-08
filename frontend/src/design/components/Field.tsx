import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
  type Ref,
  type TextareaHTMLAttributes,
} from 'react'
import styles from './Field.module.css'
import { Icon, type IconName } from './Icon'

export interface FieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'type' | 'prefix' | 'suffix'> {
  label?: string
  type?: string
  icon?: IconName
  trailing?: ReactNode
  error?: string
  helper?: string
  multiline?: boolean
  optional?: boolean
  rows?: number
  prefix?: ReactNode
  suffix?: ReactNode
}

// Forwards a ref and spreads native input attributes directly so it wires
// straight into react-hook-form's register()/Controller without a
// wrapper-around-a-wrapper: <Field label="Email" {...register('email')} error={errors.email?.message} />
export const Field = forwardRef<HTMLInputElement | HTMLTextAreaElement, FieldProps>(
  function Field(
    {
      label,
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
      ...rest
    },
    ref,
  ) {
    const fieldId = id ?? rest.name

    return (
      <div className={styles.fieldRoot}>
        {label && (
          <label className={styles.label} htmlFor={fieldId}>
            <span>
              {label}
              {required && <span className={styles.required}>*</span>}
            </span>
            {optional && <span className={styles.optionalTag}>Optional</span>}
          </label>
        )}
        <div
          className={[
            styles.wrapper,
            multiline ? styles.multiline : '',
            error ? styles.wrapperError : '',
            disabled ? styles.wrapperDisabled : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          {icon && <Icon name={icon} size={16} color="var(--color-ink-4)" />}
          {prefix && <span className={styles.prefix}>{prefix}</span>}
          {multiline ? (
            <textarea
              id={fieldId}
              ref={ref as Ref<HTMLTextAreaElement>}
              rows={rows}
              required={required}
              disabled={disabled}
              className={styles.textarea}
              // The common subset of attributes (value/onChange/onBlur/name/placeholder/...)
              // is identical between input and textarea; only `type` (excluded above) and
              // a handful of input-only attributes diverge, so this cast is safe in practice.
              {...(rest as unknown as TextareaHTMLAttributes<HTMLTextAreaElement>)}
            />
          ) : (
            <input
              id={fieldId}
              ref={ref as Ref<HTMLInputElement>}
              type={type}
              required={required}
              disabled={disabled}
              className={styles.input}
              {...rest}
            />
          )}
          {suffix && <span className={styles.suffix}>{suffix}</span>}
          {trailing}
        </div>
        {error && (
          <div className={styles.errorMsg}>
            <Icon name="alert" size={12} color="var(--color-error)" />
            {error}
          </div>
        )}
        {helper && !error && <div className={styles.helper}>{helper}</div>}
      </div>
    )
  },
)
