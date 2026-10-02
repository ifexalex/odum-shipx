import { useEffect, type ButtonHTMLAttributes, type JSX } from 'react'
import styles from './Button.module.css'
import { Icon, type IconName } from './Icon'

export type ButtonVariant =
  | 'primary'
  | 'accent'
  | 'secondary'
  | 'ghost'
  | 'danger'
  | 'danger-outline'
  | 'success'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: IconName
  trailingIcon?: IconName
  loading?: boolean
  full?: boolean
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: styles.primary!,
  accent: styles.accent!,
  secondary: styles.secondary!,
  ghost: styles.ghost!,
  danger: styles.danger!,
  'danger-outline': styles.dangerOutline!,
  success: styles.success!,
}

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: styles.sm!,
  md: styles.md!,
  lg: styles.lg!,
}

const ICON_SIZE: Record<ButtonSize, number> = { sm: 13, md: 15, lg: 16 }

// Module-level so the count is shared across every Button instance currently
// mounted, approximating "per screen" without a router-aware page boundary.
let mountedAccentButtons = 0

function useAccentGuard(active: boolean): void {
  useEffect(() => {
    if (!active || !import.meta.env.DEV) return undefined
    mountedAccentButtons += 1
    if (mountedAccentButtons > 1) {
      console.warn(
        `[ShipX] ${mountedAccentButtons} variant="accent" Buttons are mounted at once. ` +
          'Kola Copper is reserved for the single highest-stakes action per screen — ' +
          'demote the others to variant="primary".',
      )
    }
    return () => {
      mountedAccentButtons -= 1
    }
  }, [active])
}

export function Button({
  variant = 'primary',
  size = 'md',
  icon,
  trailingIcon,
  loading = false,
  full = false,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps): JSX.Element {
  useAccentGuard(variant === 'accent')
  const iconSize = ICON_SIZE[size]

  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={[styles.button, VARIANT_CLASS[variant], SIZE_CLASS[size], full ? styles.full : '', className]
        .filter(Boolean)
        .join(' ')}
    >
      {loading ? (
        <span className={styles.spinner} aria-hidden="true" />
      ) : (
        icon && <Icon name={icon} size={iconSize} stroke={2.2} />
      )}
      {children}
      {!loading && trailingIcon && <Icon name={trailingIcon} size={iconSize} stroke={2.2} />}
    </button>
  )
}
