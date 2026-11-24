/**
 * Button (FD-07). Five variants and one exception:
 *
 *   primary       the main action of a screen or dialog. One per area.
 *   secondary     every other action; the only button a table row may carry (size sm).
 *   ghost         low-emphasis actions beside others: "Cancel", "Clear", "Remove".
 *   danger        an irreversible commit ("Delete warehouse"), usually the dialog's confirm button.
 *   danger-ghost  the way into something destructive ("Cancel container", "Suspend"), never filled beside a primary.
 *   accent        reserved for paying and signing in (Kola copper). A test keeps it to those screens.
 *
 * Heights 32 / 40 / 48 px (sm / md / lg); 44 px minimum on touch screens. Put direction in `trailingIcon`, never an
 * arrow typed into the label. A button that changes data (`mutates`, on by default for primary, accent, danger and
 * danger-ghost) is disabled during read-only impersonation, so no page needs its own check.
 */
import { useContext, type ButtonHTMLAttributes, type JSX } from 'react'
import { SessionContext } from '../../auth/SessionContext'
import styles from './Button.module.css'
import { Icon, type IconName } from './Icon'

export type ButtonVariant = 'primary' | 'accent' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: IconName
  trailingIcon?: IconName
  loading?: boolean
  full?: boolean
  /** Whether the button changes data. Default: true for primary, accent, danger and danger-ghost. */
  mutates?: boolean
}

export const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: styles.primary!,
  accent: styles.accent!,
  secondary: styles.secondary!,
  ghost: styles.ghost!,
  danger: styles.danger!,
  'danger-ghost': styles.dangerGhost!,
}

export const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: styles.sm!,
  md: styles.md!,
  lg: styles.lg!,
}

export const ICON_SIZE: Record<ButtonSize, number> = { sm: 14, md: 16, lg: 18 }

const MUTATING_BY_DEFAULT: ReadonlySet<ButtonVariant> = new Set(['primary', 'accent', 'danger', 'danger-ghost'])

/** True while a platform admin views the tenant read-only and this button would change data. */
export function useReadOnlyBlock(variant: ButtonVariant, mutates: boolean | undefined): boolean {
  const session = useContext(SessionContext)?.session
  return Boolean(session?.readOnly) && (mutates ?? MUTATING_BY_DEFAULT.has(variant))
}

export const READ_ONLY_TITLE = 'Disabled during read-only impersonation'

export function Button({
  variant = 'primary',
  size = 'md',
  icon,
  trailingIcon,
  loading = false,
  full = false,
  mutates,
  disabled,
  children,
  className,
  title,
  ...rest
}: ButtonProps): JSX.Element {
  const blocked = useReadOnlyBlock(variant, mutates)
  const iconSize = ICON_SIZE[size]

  return (
    <button
      type="button"
      {...rest}
      title={blocked ? READ_ONLY_TITLE : title}
      aria-disabled={blocked || undefined}
      disabled={disabled || loading || blocked}
      className={[
        styles.button,
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        full ? styles.full : '',
        blocked ? styles.readOnly : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {loading ? (
        <span className={styles.spinner} aria-hidden="true" />
      ) : blocked ? (
        <Icon name="suspend" size={iconSize} stroke={2.2} />
      ) : (
        icon && <Icon name={icon} size={iconSize} stroke={2.2} />
      )}
      {children}
      {!loading && !blocked && trailingIcon && <Icon name={trailingIcon} size={iconSize} stroke={2.2} />}
    </button>
  )
}
