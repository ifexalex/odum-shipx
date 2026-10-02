import type { JSX, ReactNode } from 'react'
import styles from './Chip.module.css'
import { Icon } from './Icon'

export interface ChipProps {
  children: ReactNode
  active?: boolean
  count?: number
  dismissible?: boolean
  onClick?: () => void
  onDismiss?: () => void
}

// Rendered as a <span> wrapper with two sibling <button>s (label, dismiss)
// rather than nesting a dismiss button inside the clickable chip — a button
// cannot validly contain another interactive element.
export function Chip({
  children,
  active = false,
  count,
  dismissible = false,
  onClick,
  onDismiss,
}: ChipProps): JSX.Element {
  return (
    <span className={[styles.chip, active ? styles.active : ''].filter(Boolean).join(' ')}>
      <button type="button" className={styles.label} onClick={onClick}>
        {children}
        {count != null && <span className={styles.count}>{count}</span>}
      </button>
      {dismissible && (
        <button type="button" aria-label="Remove" className={styles.dismiss} onClick={onDismiss}>
          <Icon name="x" size={11} stroke={2.5} />
        </button>
      )}
    </span>
  )
}
