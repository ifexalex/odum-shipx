import type { JSX, ReactNode } from 'react'
import styles from './PageHeader.module.css'

export interface PageHeaderProps {
  title: string
  subtitle?: string
  eyebrow?: string
  actions?: ReactNode
}

export function PageHeader({ title, subtitle, eyebrow, actions }: PageHeaderProps): JSX.Element {
  return (
    <div className={styles.header}>
      <div className={styles.titleBlock}>
        {eyebrow && <div className={styles.eyebrow}>{eyebrow}</div>}
        <h2 className={styles.title}>{title}</h2>
        {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  )
}
