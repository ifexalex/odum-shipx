/**
 * StatusBadge — a record's status in the registry's words and colour (FD-08). Every page shows status through this,
 * so a sealed container or a partly paid invoice reads and looks the same everywhere.
 *
 *   <StatusBadge kind="container" status={container.status} />
 *   <StatusBadge kind="invoice" status={billing.payment_status} audience="customer" />
 */
import type { JSX } from 'react'
import { type Audience, type StatusKind, type StatusOf, statusLabel, statusVariant } from '../status'
import { Badge, type BadgeSize } from './Badge'

export interface StatusBadgeProps<K extends StatusKind> {
  kind: K
  status: StatusOf<K> | string
  /** Customers read their own words for some statuses (default: staff). */
  audience?: Audience
  size?: BadgeSize
}

export function StatusBadge<K extends StatusKind>({ kind, status, audience = 'staff', size }: StatusBadgeProps<K>): JSX.Element {
  return (
    <Badge variant={statusVariant(kind, status)} size={size}>
      {statusLabel(kind, status, audience)}
    </Badge>
  )
}
