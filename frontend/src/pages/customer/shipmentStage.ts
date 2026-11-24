/**
 * Where a customer's shipment is, in the customer's words (FD-27): which count it belongs to on "My shipments" and
 * how its arrival date is labelled. Derived from the container status alone, so the page, its counts and its tests
 * agree.
 */
import { formatDate, todayIso } from '../../lib/format'

/** Still on its way to the warehouse: loading in China, at sea, or at the Nigerian port and customs. */
const IN_TRANSIT = new Set(['loading', 'sealed', 'in_transit', 'arrived', 'customs_clearance', 'cleared'])
/** Container statuses once the container has reached Nigeria. */
const ARRIVED = new Set(['arrived', 'customs_clearance', 'cleared', 'at_warehouse', 'fully_released'])

export type ShipmentStage = 'in_transit' | 'ready_for_pickup' | 'complete'

/** The stage a container status puts a shipment in, or null for one that is neither active nor complete. */
export function shipmentStage(containerStatus: string | null | undefined): ShipmentStage | null {
  if (!containerStatus) return null
  if (containerStatus === 'at_warehouse') return 'ready_for_pickup'
  if (IN_TRANSIT.has(containerStatus)) return 'in_transit'
  if (containerStatus === 'fully_released' || containerStatus === 'cancelled') return 'complete'
  return null
}

/** "3 in transit, 2 ready for pickup": the active shipments by stage, leaving out a stage with none. */
export function activeSummary(statuses: readonly (string | null | undefined)[]): string | null {
  const inTransit = statuses.filter((s) => shipmentStage(s) === 'in_transit').length
  const ready = statuses.filter((s) => shipmentStage(s) === 'ready_for_pickup').length
  const parts = [inTransit > 0 && `${inTransit} in transit`, ready > 0 && `${ready} ready for pickup`].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : null
}

export interface ArrivalLabel {
  /** "Arrived", "Delayed" or "Expected arrival". */
  label: string
  /** The date line under it, if there is one to show. */
  detail: string | null
}

/**
 * How the arrival is labelled on a shipment card. Once the container has reached Nigeria it says "Arrived" (the
 * packing list carries only the expected date, so no date is claimed for it). Before then, an expected date already
 * past says "Delayed", in neutral text, rather than presenting a date two months gone as the plan.
 *
 * @param today The local date as YYYY-MM-DD; a parameter so tests can fix it.
 */
export function arrivalLabel(
  containerStatus: string | null | undefined,
  eta: string | null | undefined,
  today: string,
): ArrivalLabel | null {
  if (containerStatus && ARRIVED.has(containerStatus)) return { label: 'Arrived', detail: null }
  if (!eta) return null
  if (todayIso(new Date(eta)) < today) return { label: 'Delayed', detail: `Was expected ${formatDate(eta)}` }
  return { label: 'Expected arrival', detail: formatDate(eta) }
}
