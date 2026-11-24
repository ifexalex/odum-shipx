/**
 * Action — kept for the call sites that predate FD-07: a Button that always counts as changing data, so it is
 * disabled during read-only impersonation even when its variant is secondary or ghost. New code uses Button (which
 * does this by default for primary, accent, danger and danger-ghost) or Button with `mutates`.
 */
import type { JSX } from 'react'
import { Button, type ButtonProps } from './Button'

export type ActionProps = ButtonProps

export function Action(props: ActionProps): JSX.Element {
  return <Button mutates {...props} />
}
