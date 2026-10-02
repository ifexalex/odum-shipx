import type { JSX } from 'react'
import styles from './ViewLink.module.css'

export interface ViewLinkProps {
  onClick?: () => void
}

export function ViewLink({ onClick }: ViewLinkProps): JSX.Element {
  return (
    <button type="button" className={styles.link} onClick={onClick}>
      View
    </button>
  )
}
