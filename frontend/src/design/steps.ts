/**
 * The steps of each status pipeline (FD-09), named from the status registry so a stepper and a badge never disagree.
 * The second line ("At sea", "For pickup") says where the cargo is at that step.
 */
import type { ContainerStatus } from '../api/tracking'
import { CLAIM_STATUS_ORDER } from '../api/claimsRules'
import type { StepperStep } from './components/Stepper'
import { statusLabel, type Audience } from './status'

const CONTAINER_STEPS: Array<{ status: ContainerStatus; sub: string; tone: 'china' | 'nigeria' }> =
  [
    { status: 'loading', sub: 'China warehouse', tone: 'china' },
    { status: 'sealed', sub: 'Container sealed', tone: 'china' },
    { status: 'in_transit', sub: 'At sea', tone: 'china' },
    { status: 'arrived', sub: 'Tin Can Port', tone: 'nigeria' },
    { status: 'customs_clearance', sub: 'Clearance', tone: 'nigeria' },
    { status: 'cleared', sub: 'Released by customs', tone: 'nigeria' },
    { status: 'at_warehouse', sub: 'Ready for pickup', tone: 'nigeria' },
    { status: 'fully_released', sub: 'Collected', tone: 'nigeria' },
  ]

/** A container's journey, China to collection. */
export function containerSteps(audience: Audience = 'staff'): StepperStep[] {
  return CONTAINER_STEPS.map(({ status, sub, tone }) => ({
    key: status,
    label: statusLabel('container', status, audience),
    sub,
    tone,
  }))
}

/** Where a container status sits on its journey: the index, and whether the journey is over. */
export function containerProgress(status: string | null | undefined): {
  current: number
  complete: boolean
} {
  const current = CONTAINER_STEPS.findIndex((s) => s.status === status)
  return { current, complete: status === 'fully_released' }
}

/** A damage claim, filed to closed. */
export function claimSteps(audience: Audience = 'staff'): StepperStep[] {
  return CLAIM_STATUS_ORDER.map((status) => ({
    key: status,
    label: statusLabel('claim', status, audience),
  }))
}

export function claimProgress(status: string): { current: number; complete: boolean } {
  return {
    current: CLAIM_STATUS_ORDER.indexOf(status as (typeof CLAIM_STATUS_ORDER)[number]),
    complete: status === 'closed',
  }
}
