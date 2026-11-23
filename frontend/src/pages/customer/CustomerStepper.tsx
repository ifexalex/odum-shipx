import type { JSX } from 'react'
import { Icon } from '../../design/components'
import { colors } from '../../design/theme'
import { ScrollStrip } from '../../shell/ScrollStrip'

const STAGES = [
  { status: 'loading',           label: 'Received',   sub: 'China warehouse',  side: 'cn' },
  { status: 'sealed',            label: 'Packed',     sub: 'Container sealed', side: 'cn' },
  { status: 'in_transit',        label: 'In transit', sub: 'At sea',           side: 'cn' },
  { status: 'arrived',           label: 'Arrived NG', sub: 'Tin Can Port',     side: 'ng' },
  { status: 'customs_clearance', label: 'Customs',    sub: 'Clearance',        side: 'ng' },
  { status: 'cleared',           label: 'Cleared',    sub: 'Released',         side: 'ng' },
  { status: 'at_warehouse',      label: 'Ready',      sub: 'For pickup',       side: 'ng' },
  { status: 'fully_released',    label: 'Delivered',  sub: 'Done',             side: 'ng' },
] as const

export function CustomerStepper({ containerStatus }: { containerStatus: string | null }): JSX.Element {
  const currentIdx = STAGES.findIndex((s) => s.status === containerStatus)

  return (
    <ScrollStrip minWidth={STAGES.length * 70}>
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 4, position: 'relative' }}>
      {STAGES.map((stage, i) => {
        const done = i < currentIdx
        const isCurrent = i === currentIdx
        const color = stage.side === 'cn' ? colors.info : colors.primary

        return (
          <div
            key={stage.status}
            style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative' }}
          >
            {i > 0 && (
              <div style={{
                position: 'absolute', top: 14, right: '50%', width: '100%', height: 2,
                background: done ? color : 'var(--color-line)', zIndex: 0,
              }} />
            )}
            <div style={{
              width: 30, height: 30, borderRadius: '50%',
              background: done ? color : isCurrent ? '#fff' : 'var(--color-page)',
              border: `${isCurrent ? 3 : 2}px solid ${done || isCurrent ? color : 'var(--color-line)'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              position: 'relative', zIndex: 1,
              boxShadow: isCurrent ? `0 0 0 6px ${color}22` : 'none',
            }}>
              {done
                ? <Icon name="check" size={14} color="#fff" stroke={3} />
                : isCurrent
                  ? <div style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
                  : null}
            </div>
            <div style={{ marginTop: 8, textAlign: 'center' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: done || isCurrent ? 'var(--color-ink)' : 'var(--color-ink-4)' }}>
                {stage.label}
              </div>
              <div style={{ fontSize: 10, color: 'var(--color-ink-4)', marginTop: 1 }}>{stage.sub}</div>
            </div>
          </div>
        )
      })}
    </div>
    </ScrollStrip>
  )
}
