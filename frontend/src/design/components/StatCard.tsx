import type { JSX, ReactNode } from 'react'
import { Card } from './Card'
import { Icon, type IconName } from './Icon'
import styles from './StatCard.module.css'

export interface StatCardTrend {
  direction: 'up' | 'down'
  pct: number
}

export interface StatCardProps {
  label: string
  value: ReactNode
  suffix?: string
  trend?: StatCardTrend
  sublabel?: string
  icon?: IconName
  accentColor?: string
}

export function StatCard({
  label,
  value,
  suffix,
  trend,
  sublabel,
  icon,
  accentColor,
}: StatCardProps): JSX.Element {
  return (
    <Card padding={20} radius={12}>
      <div className={styles.head}>
        {icon && (
          <div className={styles.iconSlot} style={accentColor ? { color: accentColor } : undefined}>
            <Icon name={icon} size={16} />
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
              className={[styles.trend, trend.direction === 'down' ? styles.trendDown : styles.trendUp].join(
                ' ',
              )}
            >
              <Icon name={trend.direction === 'down' ? 'arrowdown' : 'arrowup'} size={11} stroke={2.8} />
              {trend.pct}%
            </span>
          )}
          {sublabel && <span className={styles.sublabel}>{sublabel}</span>}
        </div>
      )}
    </Card>
  )
}
