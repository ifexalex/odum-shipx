import { type JSX } from 'react'
import { Card, Stepper } from '../../../design/components'

export interface WizardStepsProps {
  current: 1 | 2 | 3
}

const STEPS = [
  { key: 'details', label: 'Details', sub: 'Customer + container' },
  { key: 'items', label: 'Items', sub: 'Cartons + measurements' },
  { key: 'review', label: 'Review', sub: 'Verify + submit' },
]

/** The packing-list form's three steps (FD-09: the shared Stepper in wizard mode). */
export function WizardSteps({ current }: WizardStepsProps): JSX.Element {
  return (
    <Card padding="default">
      <Stepper mode="wizard" steps={STEPS} current={current - 1} label="Packing list steps" />
    </Card>
  )
}
