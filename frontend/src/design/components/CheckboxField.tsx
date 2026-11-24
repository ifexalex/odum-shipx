/**
 * CheckboxField — one labelled checkbox with an optional line of explanation (FD-11): "Release with an outstanding
 * balance". The whole row is the click target.
 */
import type { InputHTMLAttributes, JSX, ReactNode } from 'react'
import styles from './Field.module.css'

export interface CheckboxFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange' | 'children'> {
  label: ReactNode
  hint?: ReactNode
  checked: boolean
  onChange: (checked: boolean) => void
}

export function CheckboxField({ label, hint, checked, onChange, className, ...rest }: CheckboxFieldProps): JSX.Element {
  return (
    <label className={[styles.checkboxField, className].filter(Boolean).join(' ')}>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} {...rest} />
      <span>
        {label}
        {hint && <span className={styles.radioHint}>{hint}</span>}
      </span>
    </label>
  )
}
