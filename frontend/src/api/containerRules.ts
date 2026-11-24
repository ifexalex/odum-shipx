import type { UserRole } from '../auth/types'
import type { ContainerStatus } from './tracking'

// Ground truth: services/tracking/service.py's update_container_status() —
// the FROM-status determines which jurisdiction may move it forward, and
// at_warehouse->fully_released is reserved for tenant_admin/warehouse_attendant.
const CHINA_OWNED_FROM: ContainerStatus[] = ['loading', 'sealed']
const NIGERIA_OWNED_FROM: ContainerStatus[] = ['in_transit', 'arrived', 'customs_clearance', 'cleared']

const NEXT_STATUS: Record<ContainerStatus, ContainerStatus | null> = {
  loading: 'sealed',
  sealed: 'in_transit',
  in_transit: 'arrived',
  arrived: 'customs_clearance',
  customs_clearance: 'cleared',
  cleared: 'at_warehouse',
  at_warehouse: 'fully_released',
  fully_released: null,
  cancelled: null,
}

export const CONTAINER_STATUS_ORDER: ContainerStatus[] = [
  'loading',
  'sealed',
  'in_transit',
  'arrived',
  'customs_clearance',
  'cleared',
  'at_warehouse',
  'fully_released',
]

/** True when a container can be hard-deleted (no cargo, still loading). */
export function canDeleteContainer(
  role: UserRole,
  status: ContainerStatus,
  packingListCount: number,
): boolean {
  if (role !== 'china_office_staff' && role !== 'tenant_admin') return false
  return status === 'loading' && packingListCount === 0
}

/** True when a container can be soft-cancelled (China-side, before going to sea). */
export function canCancelContainer(role: UserRole, status: ContainerStatus): boolean {
  if (role !== 'china_office_staff' && role !== 'tenant_admin') return false
  return status === 'loading' || status === 'sealed'
}

/** The only legal forward status, or null if this is the terminal stage. Transitions are sequential, never skippable. */
export function nextContainerStatus(current: ContainerStatus): ContainerStatus | null {
  return NEXT_STATUS[current]
}

/** Whether `role` may advance the container out of its current status, per jurisdiction. */
export function canAdvanceContainerStatus(role: UserRole, current: ContainerStatus): boolean {
  if (CHINA_OWNED_FROM.includes(current)) return role === 'china_office_staff' || role === 'tenant_admin'
  if (NIGERIA_OWNED_FROM.includes(current)) return role === 'nigeria_office_staff' || role === 'tenant_admin'
  if (current === 'at_warehouse') return role === 'tenant_admin' || role === 'warehouse_attendant'
  return false
}

/**
 * Advisory copy for pre-transition guards the backend enforces server-side
 * (NO_APPROVED_PACKING_LISTS / NO_MANIFEST / MISSING_SHIP_DATE) — shown so
 * the UI doesn't just surface a raw 422 after the user clicks through.
 */
export function containerAdvanceRequirementHint(target: ContainerStatus): string | null {
  if (target === 'sealed') return 'Requires at least 1 approved packing list and a verified manifest.'
  if (target === 'in_transit') return 'Requires a ship date.'
  return null
}

// ---------------------------------------------------------------------------
// Container utilization (shared by ContainerList + ContainerDetail)
// ---------------------------------------------------------------------------

/** Approximate usable capacity (m³) by free-text container type — a fallback
 *  for containers created before capacity presets (migration 051), which carry
 *  an exact `capacity_cbm`. Returns null when the type is unknown, so callers
 *  hide the bar rather than show a fabricated %. */
export function containerCapacityCbm(type: string | null | undefined): number | null {
  if (!type) return null
  const t = type.toLowerCase()
  if (t.includes('45')) return 86
  if (t.includes('hc') || t.includes('high cube')) return 76
  if (t.includes('40')) return 67
  if (t.includes('20')) return 33
  return null
}

export type UtilizationLevel = 'green' | 'yellow' | 'red'

/** Business rule (7.84): a container is well-loaded by *absolute* packed CBM,
 *  not % of capacity — ≥70 green, 65–69 yellow, <65 red (the stated "50 and
 *  below" falls in red). Tuned to the standard 40ft container. */
export function utilizationLevel(packedCbm: number): UtilizationLevel {
  if (packedCbm >= 70) return 'green'
  if (packedCbm >= 65) return 'yellow'
  return 'red'
}
