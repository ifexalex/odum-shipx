import { type JSX } from 'react'
import { Card, Icon } from '../../../design/components'
import styles from '../CreatePackingList.module.css'

export interface WizardStepsProps {
  current: 1 | 2 | 3
}

export function WizardSteps({ current }: WizardStepsProps): JSX.Element {
  const steps: { n: 1 | 2 | 3; label: string; sub: string }[] = [
    { n: 1, label: 'Details', sub: 'Customer + container' },
    { n: 2, label: 'Items', sub: 'Cartons + measurements' },
    { n: 3, label: 'Review', sub: 'Verify + submit' },
  ]
  return (
    <Card padding={0}>
      <div className={styles.steps}>
        {steps.map((step, index) => {
          const done = step.n < current
          const isCurrent = step.n === current
          return (
            <div key={step.n} className={styles.stepWrap}>
              <div className={[styles.step, isCurrent ? styles.stepActive : ''].join(' ')}>
                <div
                  className={[
                    styles.stepCircle,
                    done ? styles.stepDone : '',
                    isCurrent ? styles.stepCurrent : '',
                  ].join(' ')}
                >
                  {done ? <Icon name="check" size={16} stroke={3} color="#fff" /> : step.n}
                </div>
                <div className={styles.stepText}>
                  <div className={styles.stepEyebrow}>Step {step.n}</div>
                  <div
                    className={[
                      styles.stepLabel,
                      done || isCurrent ? '' : styles.stepLabelIdle,
                    ].join(' ')}
                  >
                    {step.label}
                  </div>
                  <div className={styles.stepSub}>{step.sub}</div>
                </div>
              </div>
              {index < steps.length - 1 && (
                <Icon name="chevright" size={14} color="var(--color-ink-4)" />
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}
