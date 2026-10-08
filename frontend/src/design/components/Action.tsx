/**
 * Action — a mutating-button wrapper that enforces read-only impersonation.
 *
 * When the active session is read-only (`session.readOnly === true`) every
 * Action renders as a disabled dashed pill rather than a live Button — no
 * per-page `if (readOnly)` checks needed.
 *
 * Use exactly like Button:
 *   <Action variant="primary" icon="check">Approve</Action>
 *
 * The component reads the session from context internally — callers do not
 * need to thread `readOnly` down as a prop.
 */
import type { JSX, ReactNode } from 'react'
import { useSession } from '../../auth/useSession'
import { Button, type ButtonProps } from './Button'
import { Icon } from './Icon'
import styles from './Action.module.css'

export interface ActionProps extends ButtonProps {
  children?: ReactNode
}

export function Action({ children, ...buttonProps }: ActionProps): JSX.Element {
  const { session } = useSession()
  const readOnly = session?.readOnly ?? false

  if (readOnly) {
    return (
      <span
        className={styles.readOnly}
        title="Disabled during read-only impersonation"
        aria-disabled="true"
        role="button"
      >
        <Icon name="suspend" size={13} color="var(--color-ink-4)" />
        {children}
      </span>
    )
  }

  return <Button {...buttonProps}>{children}</Button>
}
