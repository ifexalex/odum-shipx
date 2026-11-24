import type { JSX } from 'react'
import { Stepper } from '../../design/components'
import { containerProgress, containerSteps } from '../../design/steps'

/**
 * Where the customer's cargo is (FD-09): the shared Stepper with the customer's wording. Below 600 px it shows the
 * current step, "3 of 8" and a bar, so it fits a phone without scrolling.
 */
export function CustomerStepper({ containerStatus }: { containerStatus: string | null }): JSX.Element {
  const progress = containerProgress(containerStatus)
  return (
    <Stepper steps={containerSteps('customer')} current={progress.current} complete={progress.complete} label="Shipment progress" />
  )
}
