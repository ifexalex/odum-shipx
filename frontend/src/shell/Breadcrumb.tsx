import type { JSX } from 'react'
import { Link } from 'react-router-dom'
import type { Crumb } from './breadcrumbs'
import styles from './Breadcrumb.module.css'

/**
 * Where the page lives, as links back up (audit FD-45). Every crumb but the last is a link; the last is the current
 * page. Below 600 px the trail gives way to one back link to the parent. Renders nothing for an empty trail (a
 * top-level page).
 */
export function Breadcrumb({ trail }: { trail: Crumb[] }): JSX.Element | null {
  if (trail.length === 0) return null
  const parent = trail.slice(0, -1).at(-1)
  return (
    <nav aria-label="Breadcrumb" className={styles.nav}>
      <ol className={styles.list}>
        {trail.map((crumb, index) => (
          <li key={crumb.to ?? `current-${index}`} className={styles.item}>
            {crumb.to ? (
              <Link to={crumb.to} className={styles.link}>
                {crumb.label}
              </Link>
            ) : (
              <span aria-current="page" className={styles.current}>
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
      {parent?.to && (
        <Link to={parent.to} className={styles.back}>
          <span aria-hidden="true">←</span> {parent.label}
        </Link>
      )}
    </nav>
  )
}
