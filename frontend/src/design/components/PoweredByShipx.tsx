import type { JSX } from 'react'
import { KolaMark } from './KolaMark'
import { ShipxWordmark } from './ShipxWordmark'
import styles from './PoweredByShipx.module.css'

export interface PoweredByShipxProps {
  /** 'dark' on dark branded chrome (sidebar); 'light' on page/drawer surfaces. */
  surface?: 'dark' | 'light'
  /** Collapsed sidebar mode: icon mark only with accessible label. */
  compact?: boolean
}

/**
 * Subtle platform attribution shown in tenant-branded shells (staff sidebar
 * footer, customer portal footer, public tracking page) so users know the
 * software is powered by ShipX while the tenant owns the primary brand slot.
 */
export function PoweredByShipx({ surface = 'light', compact = false }: PoweredByShipxProps): JSX.Element {
  const isDark = surface === 'dark'
  if (compact) {
    return (
      <div
        className={[styles.root, isDark ? styles.onDark : styles.onLight, styles.compact].join(' ')}
        title="Powered by ShipX"
        aria-label="Powered by ShipX"
      >
        <KolaMark size={16} color={isDark ? 'var(--color-primary-bright)' : 'var(--color-primary-text)'} />
      </div>
    )
  }

  return (
    <div className={[styles.root, isDark ? styles.onDark : styles.onLight].join(' ')}>
      <span className={styles.prefix}>Powered by</span>
      <span className={styles.mark}>
        <KolaMark size={14} color={isDark ? 'var(--color-primary-bright)' : 'var(--color-primary-text)'} />
        <ShipxWordmark
          size={13}
          color={isDark ? 'var(--color-on-dark-muted)' : 'var(--color-ink-3)'}
          xColor={isDark ? 'var(--color-primary-bright)' : 'var(--color-accent-text)'}
        />
      </span>
    </div>
  )
}
