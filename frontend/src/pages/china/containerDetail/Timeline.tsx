import { type JSX } from 'react'
import { CONTAINER_STATUS_LABELS } from '../../../api/containerRules'
import { type ContainerEvent, type ContainerStatus } from '../../../api/tracking'
import { Icon } from '../../../design/components'
import styles from '../ContainerDetail.module.css'
import { formatDate } from '../../../lib/format'
import { eventIconForStatus } from './labels'
import { ScrollStrip } from '../../../shell/ScrollStrip'

// Stepper stage config — display labels/subs match the prototype exactly.
// Backend status keys are unchanged; only the visual pipeline uses these.
const STEPPER_STAGES: Array<{
  status: ContainerStatus
  label: string
  sub: string
  side: 'china' | 'ng'
}> = [
  { status: 'loading', label: 'Received', sub: 'China warehouse', side: 'china' },
  { status: 'sealed', label: 'Packed', sub: 'Container sealed', side: 'china' },
  { status: 'in_transit', label: 'In transit', sub: 'At sea', side: 'china' },
  { status: 'arrived', label: 'Arrived NG', sub: 'Tin Can Port', side: 'ng' },
  { status: 'customs_clearance', label: 'Customs', sub: 'Clearance', side: 'ng' },
  { status: 'cleared', label: 'Cleared', sub: 'Released', side: 'ng' },
  { status: 'at_warehouse', label: 'Ready', sub: 'For pickup', side: 'ng' },
  { status: 'fully_released', label: 'Completed', sub: 'Delivered', side: 'ng' },
]

export function ContainerStepper({ current }: { current: ContainerStatus }): JSX.Element {
  const currentIndex = STEPPER_STAGES.findIndex((s) => s.status === current)
  return (
    <ScrollStrip minWidth={STEPPER_STAGES.length * 70}>
      <div className={styles.stepper}>
        {STEPPER_STAGES.map(({ status, label, sub, side }, index) => {
          const done = index < currentIndex
          const isCurrent = index === currentIndex
          const color = side === 'china' ? 'var(--color-info)' : 'var(--color-primary)'
          return (
            <div key={status} className={styles.step}>
              {/* Connecting line to previous step */}
              {index > 0 && (
                <div
                  className={styles.stepLine}
                  style={{ background: done ? color : 'var(--color-line)' }}
                />
              )}
              <div
                className={styles.stepDot}
                style={{
                  background: done ? color : isCurrent ? '#fff' : 'var(--color-surface-muted)',
                  border: `${isCurrent ? 3 : 2}px solid ${done || isCurrent ? color : 'var(--color-line-strong)'}`,
                  boxShadow: isCurrent ? `0 0 0 6px ${color}22` : 'none',
                }}
              >
                {done ? (
                  <Icon name="check" size={14} color="#fff" stroke={3} />
                ) : isCurrent ? (
                  <span className={styles.stepDotInner} style={{ background: color }} />
                ) : null}
              </div>
              <div className={styles.stepText}>
                <div
                  className={[
                    styles.stepLabel,
                    done || isCurrent ? styles.stepLabelActive : '',
                  ].join(' ')}
                >
                  {label}
                </div>
                <div className={styles.stepSub}>{sub}</div>
                {isCurrent && (
                  <div className={styles.stepNow} style={{ background: color }}>
                    Now
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </ScrollStrip>
  )
}

export function SummaryTile({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string | number
  sub?: string
  accent?: boolean
}): JSX.Element {
  return (
    <div className={styles.summaryTile}>
      <div className={styles.summaryLabel}>{label}</div>
      <div className={[styles.summaryValue, accent ? styles.summaryValueAccent : ''].join(' ')}>
        {value}
      </div>
      {sub && <div className={styles.summarySub}>{sub}</div>}
    </div>
  )
}

export function EventRow({ event, last }: { event: ContainerEvent; last: boolean }): JSX.Element {
  const stage = STEPPER_STAGES.find((s) => s.status === event.to_status)
  const toLabel =
    stage?.label ?? CONTAINER_STATUS_LABELS[event.to_status as ContainerStatus] ?? event.to_status
  const { icon, color } = eventIconForStatus(event.to_status)
  const when = formatDate(event.created_at, 'short')
  return (
    <div className={[styles.eventRow, last ? styles.eventRowLast : ''].join(' ')}>
      <div className={styles.eventIcon} style={{ background: `${color}18`, color }}>
        <Icon name={icon} size={14} />
      </div>
      <div className={styles.eventBody}>
        <div className={styles.eventTitle}>{toLabel}</div>
        {event.notes && <div className={styles.eventSub}>{event.notes}</div>}
      </div>
      <div className={styles.eventWhen}>{when}</div>
    </div>
  )
}
