import type { JSX, ReactNode } from 'react'
import styles from './SectionHead.module.css'

export interface SectionHeadProps {
  title: string
  sub?: string
  action?: ReactNode
  /**
   * Heading level (FD-49). A section of the page is a second-level heading, under the page header's `<h1>`; a
   * section inside another section is level 3.
   */
  level?: 2 | 3
}

export function SectionHead({ title, sub, action, level = 2 }: SectionHeadProps): JSX.Element {
  const Heading = level === 3 ? 'h3' : 'h2'
  return (
    <div className={styles.head}>
      <div>
        <Heading className={styles.title}>{title}</Heading>
        {sub && <p className={styles.sub}>{sub}</p>}
      </div>
      {action}
    </div>
  )
}
