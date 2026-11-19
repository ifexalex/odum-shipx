import type { JSX, ReactNode } from 'react'
import styles from './ScrollStrip.module.css'

/**
 * A row that is wider than a phone on purpose (a pipeline of eight stages), scrolled sideways inside itself so the page
 * never is. `minWidth` is the width below which the row stops shrinking. Marked `data-scroll-strip` so the phone-width
 * audit treats its sideways scroll as intended.
 */
export function ScrollStrip({ minWidth, children }: { minWidth: number; children: ReactNode }): JSX.Element {
  return (
    <div className={styles.strip} data-scroll-strip="">
      <div style={{ minWidth }}>{children}</div>
    </div>
  )
}
