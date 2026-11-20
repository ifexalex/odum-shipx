import { useRef, type JSX } from 'react'
import { useIsNarrow } from '../useIsNarrow'
import { Icon } from './Icon'
import styles from './Stepper.module.css'

/** Where a step happens, for the colour of its dot and line: China-side steps are info blue, the rest brand green. */
export type StepTone = 'china' | 'nigeria'

export interface StepperStep {
  /** Stable key, usually the status the step stands for. */
  key: string
  /** The step's name. For a status pipeline, take it from the status registry (`statusLabel`). */
  label: string
  /** A short second line: "At sea", "Customer + container". */
  sub?: string
  tone?: StepTone
}

export interface StepperProps {
  steps: StepperStep[]
  /** Index of the current step; -1 when none has started. */
  current: number
  /**
   * `progress` for a status pipeline (a container, a claim, a refund); `wizard` for a numbered form, where each dot
   * shows its number and the label carries "Step n".
   */
  mode?: 'progress' | 'wizard'
  /** The current step ended in a refusal: it shows a cross in the error colour and nothing after it is reached. */
  failed?: boolean
  /** Every step is done, the current one included (a finished pipeline). */
  complete?: boolean
  /** What the steps are of, for screen readers: "Shipment progress", "Refund progress". */
  label: string
  /** At or below this width (of the stepper itself) it shows the compact form: the current step, "2 of 8" and a bar. */
  compactBelow?: number
}

const COMPACT_BELOW = 600

type StepState = 'done' | 'current' | 'failed' | 'upcoming'

function stateOf(index: number, current: number, failed: boolean, complete: boolean): StepState {
  if (complete && index <= current) return 'done'
  if (index < current) return 'done'
  if (index === current) return failed ? 'failed' : 'current'
  return 'upcoming'
}

const STATE_WORD: Record<StepState, string> = {
  done: 'done',
  current: 'current step',
  failed: 'stopped here',
  upcoming: 'not started',
}

/**
 * One stepper for every progress row in the app (FD-09). Upcoming steps stay readable; below `compactBelow` px of its
 * own width it collapses to the current step, its position and a bar, so it never runs off a phone's edge.
 */
export function Stepper({
  steps,
  current,
  mode = 'progress',
  failed = false,
  complete = false,
  label,
  compactBelow = COMPACT_BELOW,
}: StepperProps): JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  const compact = useIsNarrow(ref, compactBelow)
  const reached = Math.max(current, 0)
  const now = steps[Math.min(reached, steps.length - 1)]
  const doneCount = complete ? current + 1 : Math.max(current, 0)
  const toneClass = (step: StepperStep | undefined): string =>
    step?.tone === 'china' ? styles.toneChina! : styles.toneNigeria!

  return (
    <div ref={ref} className={styles.wrapper}>
      {compact ? (
        <div className={[styles.compact, toneClass(now), failed ? styles.isFailed : ''].join(' ')}>
          <div className={styles.compactHead}>
            <span className={styles.compactName}>
              {mode === 'wizard' ? `Step ${reached + 1}: ` : ''}
              {current < 0 ? 'Not started' : now?.label}
            </span>
            <span className={styles.compactCount}>
              {Math.min(reached + 1, steps.length)} of {steps.length}
            </span>
          </div>
          {now?.sub && current >= 0 && <div className={styles.compactSub}>{now.sub}</div>}
          <div
            className={styles.bar}
            role="progressbar"
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={steps.length}
            aria-valuenow={doneCount}
            aria-valuetext={`${now?.label ?? ''}, ${Math.min(reached + 1, steps.length)} of ${steps.length}`}
          >
            <div
              className={styles.barFill}
              style={{
                width: `${(Math.max(doneCount, failed ? reached + 1 : 0) / steps.length) * 100}%`,
              }}
            />
          </div>
        </div>
      ) : (
        <ol
          className={[styles.steps, mode === 'wizard' ? styles.wizard : ''].join(' ')}
          aria-label={label}
        >
          {steps.map((step, index) => {
            const state = stateOf(index, current, failed, complete)
            return (
              <li
                key={step.key}
                className={[styles.step, styles[state], toneClass(step)].join(' ')}
                aria-current={state === 'current' || state === 'failed' ? 'step' : undefined}
              >
                {index > 0 && <span className={styles.line} aria-hidden="true" />}
                <span className={styles.dot} aria-hidden="true">
                  {state === 'done' ? (
                    <Icon name="check" size={14} stroke={3} />
                  ) : state === 'failed' ? (
                    <Icon name="x" size={14} stroke={3} />
                  ) : mode === 'wizard' ? (
                    index + 1
                  ) : state === 'current' ? (
                    <span className={styles.dotInner} />
                  ) : null}
                </span>
                <span className={styles.text}>
                  {mode === 'wizard' && <span className={styles.eyebrow}>Step {index + 1}</span>}
                  <span className={styles.label}>{step.label}</span>
                  {step.sub && <span className={styles.sub}>{step.sub}</span>}
                  <span className={styles.srOnly}>, {STATE_WORD[state]}</span>
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
