import { utilizationLevel } from '../../../api/containerRules'
import { type PackingList } from '../../../api/packingList'
import { type BadgeVariant, type IconName } from '../../../design/components'
import styles from '../ContainerDetail.module.css'

// Maps a status transition to a human-readable event label for the event log.
export function eventLabel(from: string, to: string): string {
  if (!from) return 'Created'
  const labels: Record<string, string> = {
    sealed: 'Container sealed',
    in_transit: 'Loaded vessel',
    arrived: 'Arrived in Nigeria',
    customs_clearance: 'Customs clearance',
    at_warehouse: 'At warehouse',
    cleared: 'Cleared',
    fully_released: 'Fully released',
  }
  return labels[to] ?? `${from} → ${to}`
}

export function eventBadgeVariant(toStatus: string): BadgeVariant {
  if (['cleared', 'fully_released'].includes(toStatus)) return 'success'
  if (['arrived', 'customs_clearance', 'at_warehouse'].includes(toStatus)) return 'warning'
  return 'info'
}

// Converts backend role keys to display labels for the Updated by column.
export function humanRole(role: string | null): string {
  const map: Record<string, string> = {
    platform_admin: 'Platform Admin',
    tenant_admin: 'Admin',
    china_office_staff: 'China Office',
    nigeria_office_staff: 'Nigeria Office',
    warehouse_attendant: 'Warehouse',
    customer: 'Customer',
  }
  return role ? (map[role] ?? role) : '—'
}

export const PL_STATUS_VARIANT: Record<PackingList['status'], BadgeVariant> = {
  draft: 'neutral',
  pending_approval: 'warning',
  approved: 'success',
  rejected: 'error',
}

// Utilization colour by *absolute* packed CBM (business rule, not % of
// capacity): ≥70 green, 65–69 yellow, <65 red. Shared level logic +
// capacity estimate live in api/containerRules.ts; this maps the level to this
// page's CSS-module fill classes. See 10_api_tracking.md.
export function utilizationColorClass(packedCbm: number): string {
  const level = utilizationLevel(packedCbm)
  if (level === 'green') return styles.utilFillGreen!
  if (level === 'yellow') return styles.utilFillYellow!
  return styles.utilFillRed!
}

// Map container status transitions to meaningful icons + colors for the event log.
export function eventIconForStatus(toStatus: string): { icon: IconName; color: string } {
  if (toStatus === 'in_transit') return { icon: 'ship', color: 'var(--color-info)' }
  if (toStatus === 'sealed') return { icon: 'package', color: 'var(--color-success)' }
  if (toStatus === 'cleared' || toStatus === 'fully_released')
    return { icon: 'check', color: 'var(--color-success)' }
  if (toStatus === 'arrived' || toStatus === 'at_warehouse')
    return { icon: 'map', color: 'var(--color-warning)' }
  return { icon: 'arrowright', color: 'var(--color-ink-3)' }
}
