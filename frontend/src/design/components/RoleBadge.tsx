/**
 * RoleBadge — a person's role (FD-08). Neutral, with the role's own colour as the dot: a role is not a state, so it
 * never borrows a status colour (the Admin badge used to be the red error colour).
 */
import type { CSSProperties, JSX } from 'react'
import { roleColor, roleLabel, type TenantRole } from '../status'
import styles from './Badge.module.css'

export function RoleBadge({ role, size = 'md' }: { role: TenantRole | string; size?: 'sm' | 'md' }): JSX.Element {
  return (
    <span
      className={[styles.badge, styles.neutral, size === 'sm' ? styles.sm : ''].filter(Boolean).join(' ')}
      style={{ '--badge-dot': roleColor(role) } as CSSProperties}
    >
      <span className={styles.dot} aria-hidden="true" />
      {roleLabel(role)}
    </span>
  )
}
