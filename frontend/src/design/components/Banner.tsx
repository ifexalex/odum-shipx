import type { JSX, ReactNode } from 'react'
import styles from './Banner.module.css'
import { Icon, type IconName } from './Icon'

export type BannerVariant = 'info' | 'success' | 'warning' | 'error'

export interface BannerProps {
  variant?: BannerVariant
  title?: string
  children: ReactNode
  icon?: IconName
  action?: ReactNode
  dismissible?: boolean
  onDismiss?: () => void
}

const VARIANT_CLASS: Record<BannerVariant, string> = {
  info: styles.info!,
  success: styles.success!,
  warning: styles.warning!,
  error: styles.error!,
}

const DEFAULT_ICON: Record<BannerVariant, IconName> = {
  info: 'info',
  success: 'check',
  warning: 'warn',
  error: 'alert',
}

// Used heavily for read-only impersonation state, storage-fee grace-period
// warnings, and GDPR notices (see 08_gap_closure_features.md).
export function Banner({
  variant = 'info',
  title,
  children,
  icon,
  action,
  dismissible = false,
  onDismiss,
}: BannerProps): JSX.Element {
  return (
    <div className={[styles.banner, VARIANT_CLASS[variant]].join(' ')} role="alert">
      <Icon name={icon ?? DEFAULT_ICON[variant]} size={18} />
      <div className={styles.body}>
        {title && <div className={styles.title}>{title}</div>}
        <div>{children}</div>
      </div>
      {action}
      {dismissible && (
        <button type="button" aria-label="Dismiss" className={styles.dismiss} onClick={onDismiss}>
          <Icon name="x" size={16} />
        </button>
      )}
    </div>
  )
}
