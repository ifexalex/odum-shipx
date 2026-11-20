/**
 * QuickActionCard — dashboard task-launcher card (prototype platform-screens.jsx).
 *
 * Icon tile + title + one-line sub + CTA link. `accent` renders the copper
 * variant used to highlight the primary action in a column of cards.
 */

import type { JSX } from 'react'
import { Card } from './Card'
import { Icon, type IconName } from './Icon'
import styles from './QuickActionCard.module.css'

export interface QuickActionCardProps {
  icon: IconName
  title: string
  sub: string
  cta: string
  onAction: () => void
  accent?: boolean
}

export function QuickActionCard({ icon, title, sub, cta, onAction, accent = false }: QuickActionCardProps): JSX.Element {
  return (
    <Card padding="default">
      <div className={styles.row}>
        <div className={accent ? styles.tileAccent : styles.tile}>
          <Icon name={icon} size={18} stroke={2.3} />
        </div>
        <div className={styles.body}>
          <h3 className={styles.title}>{title}</h3>
          <p className={styles.sub}>{sub}</p>
          <button type="button" className={accent ? styles.ctaAccent : styles.cta} onClick={onAction}>
            {cta} <Icon name="arrowright" size={13} stroke={2.5} />
          </button>
        </div>
      </div>
    </Card>
  )
}
