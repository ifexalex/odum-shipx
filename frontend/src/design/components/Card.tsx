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
  /** `lg` (12 px) for a card; `xl` (16 px) for a card that is a dialog's panel (FD-04). */
  radius?: 'lg' | 'xl'
  /** Layout-only overrides (margins, overflow) merged over the base card style. */
  style?: CSSProperties
}

export function Card({ children, padding = 'default', radius = 'lg', style }: CardProps): JSX.Element {
  return (
    <div className={`${styles.card} ${PADDING_CLASS[padding]}`} style={{ borderRadius: `var(--radius-${radius})`, ...style }}>
      {children}
    </div>
  )
}
