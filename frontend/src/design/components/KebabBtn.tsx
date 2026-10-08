import type { JSX } from 'react'
import { Icon } from './Icon'
import styles from './KebabBtn.module.css'

export interface KebabBtnProps {
  onClick?: () => void
  label?: string
}

export function KebabBtn({ onClick, label = 'Row actions' }: KebabBtnProps): JSX.Element {
  return (
    <button type="button" className={styles.btn} onClick={onClick} aria-label={label}>
      <Icon name="dot3" size={16} />
    </button>
  )
}
