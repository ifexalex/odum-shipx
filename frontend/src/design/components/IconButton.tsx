/**
 * IconButton (FD-07) — a square button with only an icon. `label` is required: it is the accessible name and the
 * tooltip, so an icon button can never be unnamed (FD-50).
 *
 *   <IconButton icon="x" label="Close" onClick={onClose} />
 *   <IconButton icon="trash" label="Remove item 3" variant="danger-ghost" />
 */
import type { ButtonHTMLAttributes, JSX } from 'react'
import styles from './Button.module.css'
import { ICON_SIZE, READ_ONLY_TITLE, SIZE_CLASS, VARIANT_CLASS, useReadOnlyBlock, type ButtonSize } from './Button'
import { Icon, type IconName } from './Icon'

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'aria-label'> {
  icon: IconName
  /** What the button does, in words: "Close", "Show password", "Remove item 3". */
  label: string
  variant?: 'ghost' | 'secondary' | 'danger-ghost'
  size?: ButtonSize
  /** Whether it changes data (default: only danger-ghost does). */
  mutates?: boolean
}

export function IconButton({
  icon,
  label,
  variant = 'ghost',
  size = 'md',
  mutates,
  disabled,
  className,
  title,
  ...rest
}: IconButtonProps): JSX.Element {
  const blocked = useReadOnlyBlock(variant, mutates)
  return (
    <button
      type="button"
      {...rest}
      aria-label={label}
      title={blocked ? READ_ONLY_TITLE : (title ?? label)}
      disabled={disabled || blocked}
      className={[styles.button, styles.icon, VARIANT_CLASS[variant], SIZE_CLASS[size], blocked ? styles.readOnly : '', className]
        .filter(Boolean)
        .join(' ')}
    >
      <Icon name={blocked ? 'suspend' : icon} size={ICON_SIZE[size]} stroke={2.2} />
    </button>
  )
}
