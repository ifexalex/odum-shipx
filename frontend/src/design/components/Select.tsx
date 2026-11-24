/**
 * Select — a labelled dropdown in the Field style (FD-11). When there is nothing to choose, it says why and links
 * to where that is fixed, instead of a disabled box reading "No warehouses configured".
 *
 *   <Select label="Warehouse" value={id} onChange={(e) => setId(e.target.value)}
 *     options={warehouses.map((w) => ({ value: w.id, label: w.name }))}
 *     empty={{ message: 'No warehouses yet.', action: { label: 'Add a warehouse', to: '/admin/config/warehouses' } }} />
 */
import { forwardRef, type ReactNode, type SelectHTMLAttributes } from 'react'
import { Link } from 'react-router-dom'
import styles from './Field.module.css'
import { FieldShell } from './FieldShell'
import { Icon } from './Icon'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  label: string
  hideLabel?: boolean
  optional?: boolean
  error?: string
  helper?: ReactNode
  /** The choices. Or pass `<option>` children for groups. */
  options?: SelectOption[]
  children?: ReactNode
  /** A first, empty choice ("Choose a warehouse"). */
  placeholder?: string
  /** Shown instead of the select when there are no options: why, and the way to fix it. */
  empty?: { message: string; action?: { label: string; to: string } }
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hideLabel, optional, error, helper, options, children, placeholder, empty, id, disabled, className, ...rest },
  ref,
) {
  const hasOptions = options ? options.length > 0 : true
  return (
    <FieldShell label={label} hideLabel={hideLabel} optional={optional} error={error} helper={helper} id={id ?? rest.name} className={className}>
      {({ id: controlId, describedBy, invalid }) =>
        !hasOptions && empty ? (
          <div className={styles.emptyNote} id={controlId} role="status">
            <span>{empty.message}</span>
            {empty.action && <Link to={empty.action.to}>{empty.action.label}</Link>}
          </div>
        ) : (
          <div className={[styles.wrapper, error ? styles.wrapperError : '', disabled ? styles.wrapperDisabled : ''].filter(Boolean).join(' ')}>
            <select
              ref={ref}
              id={controlId}
              disabled={disabled}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
              className={styles.select}
              {...rest}
            >
              {placeholder !== undefined && <option value="">{placeholder}</option>}
              {options?.map((option) => (
                <option key={option.value} value={option.value} disabled={option.disabled}>
                  {option.label}
                </option>
              ))}
              {children}
            </select>
            <span className={styles.selectChevron}>
              <Icon name="chevdown" size={14} color="var(--color-ink-4)" />
            </span>
          </div>
        )
      }
    </FieldShell>
  )
})
