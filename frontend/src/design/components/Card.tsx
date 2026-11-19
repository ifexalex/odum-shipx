import type { CSSProperties, JSX, ReactNode } from 'react'
import styles from './Card.module.css'

/** A card's inner padding (FD-02): `none` for a card that holds a table edge to edge, `default` 20 px, `large` 24 px. */
export type CardPadding = 'none' | 'default' | 'large'

const PADDING_CLASS: Record<CardPadding, string | undefined> = {
  none: styles.padNone,
  default: styles.padDefault,
  large: styles.padLarge,
}

export interface CardProps {
  children: ReactNode
  padding?: CardPadding
  radius?: number
  /** Layout-only overrides (margins, overflow) merged over the base card style. */
  style?: CSSProperties
}

export function Card({ children, padding = 'default', radius = 10, style }: CardProps): JSX.Element {
  return (
    <div className={`${styles.card} ${PADDING_CLASS[padding]}`} style={{ borderRadius: radius, ...style }}>
      {children}
    </div>
  )
}
