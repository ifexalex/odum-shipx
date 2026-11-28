import { useContext, type JSX } from 'react'
import { SessionContext } from '../../auth/SessionContext'
import styles from './ToggleSwitch.module.css'

export interface ToggleSwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  /** What the switch turns on or off. Required: an unnamed switch is "switch, off" to a screen reader (FD-50). */
  label: string
}

// Used for webhook event toggles and notification preferences (08_gap_closure_features.md).
// Automatically disabled during read-only platform-admin impersonation.
export function ToggleSwitch({ checked, onChange, disabled = false, label }: ToggleSwitchProps): JSX.Element {
  const sessionCtx = useContext(SessionContext)
  const isReadOnly = Boolean(sessionCtx?.session?.readOnly)
  const effectiveDisabled = disabled || isReadOnly
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={effectiveDisabled}
      title={isReadOnly ? 'Read-only during impersonation' : undefined}
      onClick={() => !effectiveDisabled && onChange(!checked)}
      className={[styles.track, checked ? styles.checked : ''].filter(Boolean).join(' ')}
    >
      <span className={styles.thumb} />
    </button>
  )
}
