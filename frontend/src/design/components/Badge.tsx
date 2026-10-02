import type { JSX, ReactNode } from 'react'
import styles from './Badge.module.css'

export type BadgeVariant =
  | 'success'
  | 'warning'
  | 'error'
  | 'info'
  | 'accent'
  | 'purple'
  | 'neutral'
  | 'primary'
export type BadgeSize = 'sm' | 'md'

export interface BadgeProps {
  variant?: BadgeVariant
  size?: BadgeSize
  dot?: boolean
  children: ReactNode
}

const VARIANT_CLASS: Record<BadgeVariant, string> = {
  success: styles.success!,
  warning: styles.warning!,
  error: styles.error!,
  info: styles.info!,
  accent: styles.accent!,
  purple: styles.purple!,
  neutral: styles.neutral!,
  primary: styles.primary!,
}

export function Badge({
  variant = 'neutral',
  size = 'md',
  dot = true,
  children,
}: BadgeProps): JSX.Element {
  return (
    <span
      className={[styles.badge, VARIANT_CLASS[variant], size === 'sm' ? styles.sm : '']
        .filter(Boolean)
        .join(' ')}
    >
      {dot && <span className={styles.dot} aria-hidden="true" />}
      {children}
    </span>
  )
}
