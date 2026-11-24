import type { JSX, ReactNode } from 'react'
import { Card } from './Card'
import { Icon, type IconName } from './Icon'
import { Pressable } from './Pressable'
import styles from './StatCard.module.css'

export interface StatCardTrend {
  direction: 'up' | 'down'
  pct: number
}

/**
 * One number and its label (FD-10). A word or a status is not a stat: put it in the record's key-value list (`Kvp`).
 * `value` is the formatted figure: a count, an amount, "3 of 12".
 */
export interface StatCardProps {
  label: string
  value: ReactNode
  suffix?: string
  trend?: StatCardTrend
  sublabel?: string
  icon?: IconName
  accentColor?: string
  /**
   * A stat on a list page applies its filter when clicked (FD-18): "Overdue 3" shows the three. The card becomes a
   * toggle button (`aria-pressed`), outlined while its filter is on.
   */
  onSelect?: () => void
  /** Whether this stat's filter is the one applied. */
  selected?: boolean
}

export function StatCard({
  label,
  value,
  suffix,
  trend,
  sublabel,
  icon,
  accentColor,
  onSelect,
  selected = false,
}: StatCardProps): JSX.Element {
  const card = (
    <Card padding="small">
      <div className={styles.body}>
        <div className={styles.head}>
          {icon && (
            <div
              className={styles.iconSlot}
              style={accentColor ? { color: accentColor } : undefined}
            >
              <Icon name={icon} size={14} />
            </div>
          )}
          <div className={styles.label}>{label}</div>
        </div>
        <div className={styles.value}>
          {value}
          {suffix && <span className={styles.suffix}>{suffix}</span>}
        </div>
        {(trend || sublabel) && (
          <div className={styles.footRow}>
            {trend && (
              <span
                className={[
                  styles.trend,
                  trend.direction === 'down' ? styles.trendDown : styles.trendUp,
                ].join(' ')}
              >
                <Icon
                  name={trend.direction === 'down' ? 'arrowdown' : 'arrowup'}
                  size={11}
                  stroke={2.8}
                />
                {trend.pct}%
              </span>
            )}
            {sublabel && <span className={styles.sublabel}>{sublabel}</span>}
          </div>
        )}
      </div>
    </Card>
  )
  if (!onSelect) return card
  return (
    <Pressable
      className={[styles.selectable, selected ? styles.selected : ''].join(' ')}
      aria-pressed={selected}
      onClick={onSelect}
    >
      {card}
    </Pressable>
  )
}
