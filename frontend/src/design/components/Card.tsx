import type { CSSProperties, JSX, ReactNode } from 'react'
import styles from './Card.module.css'

export interface CardProps {
  children: ReactNode
  padding?: number
  radius?: number
  /** Layout-only overrides (margins, overflow) merged over the base card style. */
  style?: CSSProperties
}

export function Card({ children, padding = 24, radius = 10, style }: CardProps): JSX.Element {
  return (
    <div className={styles.card} style={{ padding, borderRadius: radius, ...style }}>
      {children}
    </div>
  )
}
