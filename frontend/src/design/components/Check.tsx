import type { JSX, KeyboardEvent } from 'react'
import styles from './Check.module.css'
import { Icon } from './Icon'

export interface CheckProps {
  checked?: boolean
  partial?: boolean
  disabled?: boolean
  onChange?: (checked: boolean) => void
}

// Checkbox primitive supporting a tri-state ("partial") visual for
// select-all headers. A real native checkbox can't render the partial dot
// with our Icon set, so this is a role="checkbox" div with full keyboard support.
export function Check({ checked = false, partial = false, disabled = false, onChange }: CheckProps): JSX.Element {
  const toggle = (): void => {
    if (disabled) return
    onChange?.(!checked)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLSpanElement>): void => {
    if (event.key !== ' ' && event.key !== 'Enter') return
    event.preventDefault()
    toggle()
  }

  return (
    <span
      role="checkbox"
      aria-checked={partial ? 'mixed' : checked}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      onClick={toggle}
      onKeyDown={handleKeyDown}
      className={[styles.check, checked || partial ? styles.active : '', disabled ? styles.disabled : '']
        .filter(Boolean)
        .join(' ')}
    >
      {checked && <Icon name="check" size={10} color="#fff" stroke={3} />}
      {!checked && partial && <Icon name="minus" size={10} color="#fff" stroke={3} />}
    </span>
  )
}
