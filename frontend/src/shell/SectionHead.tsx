import type { JSX, ReactNode } from 'react'
import styles from './SectionHead.module.css'

export interface SectionHeadProps {
  title: string
  sub?: string
  action?: ReactNode
}

export function SectionHead({ title, sub, action }: SectionHeadProps): JSX.Element {
  return (
    <div className={styles.head}>
      <div>
        <h3 className={styles.title}>{title}</h3>
        {sub && <p className={styles.sub}>{sub}</p>}
      </div>
      {action}
    </div>
  )
}
