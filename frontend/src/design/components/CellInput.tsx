/**
 * CellInput and CellSelect — compact controls for editing inside a table row (FD-11). The column header is the
 * visible label, so each needs its own `label` for screen readers, naming the row: "Weight (kg), item 3" (FD-50).
 */
import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes } from 'react'
import styles from './Field.module.css'

export interface CellInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'aria-label'> {
  label: string
}

export const CellInput = forwardRef<HTMLInputElement, CellInputProps>(function CellInput({ label, className, type, ...rest }, ref) {
  return (
    <input
      ref={ref}
      type={type}
      aria-label={label}
      className={[styles.cell, type === 'number' ? styles.cellNumber : '', className].filter(Boolean).join(' ')}
      {...rest}
    />
  )
})

export interface CellSelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'aria-label'> {
  label: string
}

export const CellSelect = forwardRef<HTMLSelectElement, CellSelectProps>(function CellSelect({ label, className, ...rest }, ref) {
  return <select ref={ref} aria-label={label} className={[styles.cell, className].filter(Boolean).join(' ')} {...rest} />
})

export interface CellCheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'aria-label'> {
  label: string
}

/** A native checkbox for a table row, named for screen readers; wrap it in a <label> with visible words if any. */
export const CellCheckbox = forwardRef<HTMLInputElement, CellCheckboxProps>(function CellCheckbox({ label, ...rest }, ref) {
  return <input ref={ref} type="checkbox" aria-label={label} style={{ accentColor: 'var(--color-primary)' }} {...rest} />
})

export interface CellRadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'aria-label'> {
  label: string
}

/** A native radio inside a row ("Primary" beside one of several roles), named for screen readers. */
export const CellRadio = forwardRef<HTMLInputElement, CellRadioProps>(function CellRadio({ label, ...rest }, ref) {
  return <input ref={ref} type="radio" aria-label={label} style={{ accentColor: 'var(--color-primary)' }} {...rest} />
})
