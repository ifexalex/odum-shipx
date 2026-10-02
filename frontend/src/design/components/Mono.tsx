import type { CSSProperties, JSX, ReactNode } from 'react'
import styles from './Mono.module.css'

export interface MonoProps {
  children: ReactNode
  color?: string
  /** Inline overrides (font-size/weight tweaks) merged over the base style. */
  style?: CSSProperties
}

// Wrap tracking codes, container numbers, and monetary amounts in this so
// table columns of these values align on a character grid (design rule, see
// 02_design_tokens_and_theming.md).
//
// Default color is the CSS token (not the static theme.ts value) so it flips
// with light/dark — a hardcoded `colors.ink` rendered near-invisible dark text
// on a dark surface. `var(--color-ink)` resolves to the same value in light.
export function Mono({ children, color = 'var(--color-ink)', style }: MonoProps): JSX.Element {
  return (
    <span className={styles.mono} style={{ color, ...style }}>
      {children}
    </span>
  )
}
