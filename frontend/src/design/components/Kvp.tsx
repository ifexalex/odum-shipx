import type { JSX, ReactNode } from 'react'
import styles from './Kvp.module.css'

export interface KvpProps {
  label: string
  value: ReactNode
  divider?: boolean
}

// Key/value detail row — recurs across every detail page's "info" card
// (container/packing-list/tenant/customer). Was duplicated ad hoc inside
// several mockup screen files rather than living in shared/components.jsx,
// so it wasn't part of Task 03's inventory; ported here once it became
// clear Task 07 needs it everywhere.
export function Kvp({ label, value, divider = true }: KvpProps): JSX.Element {
  return (
    <div className={[styles.row, divider ? '' : styles.noDivider].filter(Boolean).join(' ')}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
    </div>
  )
}
