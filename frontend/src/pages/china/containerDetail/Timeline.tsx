import { type JSX } from 'react'
import { } from '../../../api/containerRules'
import { type ContainerEvent, type ContainerStatus } from '../../../api/tracking'
import { Icon, Stepper } from '../../../design/components'
import { containerProgress, containerSteps } from '../../../design/steps'
import styles from '../ContainerDetail.module.css'
import { formatDate } from '../../../lib/format'
import { eventIconForStatus } from './labels'
import { statusLabel } from '../../../design/status'

/** The container's journey (FD-09): one shared Stepper, steps named from the status registry. */
export function ContainerStepper({ current }: { current: ContainerStatus }): JSX.Element {
  const progress = containerProgress(current)
  return <Stepper steps={containerSteps('staff')} current={progress.current} complete={progress.complete} label="Container progress" />
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
  const toLabel = statusLabel('container', event.to_status as ContainerStatus)
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
