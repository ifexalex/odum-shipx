import type { JSX } from 'react'
import styles from './ToggleSwitch.module.css'

export interface ToggleSwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  /** What the switch turns on or off. Required: an unnamed switch is "switch, off" to a screen reader (FD-50). */
  label: string
}

// Used for webhook event toggles and notification preferences (08_gap_closure_features.md).
export function ToggleSwitch({ checked, onChange, disabled = false, label }: ToggleSwitchProps): JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={[styles.track, checked ? styles.checked : ''].filter(Boolean).join(' ')}
    >
      <span className={styles.thumb} />
    </button>
  )
}
