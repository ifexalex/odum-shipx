/**
 * EmptyState (FD-20): what to show when there is nothing — an icon, a title, one line, and the next step.
 *
 * Two forms: first use ("No warehouses yet" + "Add a warehouse") and no results ("No invoices match these filters" +
 * "Clear filters"). `compact` for inside a table or a card.
 */
import type { JSX, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button } from './Button'
import { Icon, type IconName } from './Icon'
import styles from './EmptyState.module.css'

export type EmptyStateAction = { label: string; onClick: () => void } | { label: string; to: string }

export interface EmptyStateProps {
  title: string
  body?: ReactNode
  icon?: IconName
  /** The next step on first use. */
  action?: EmptyStateAction
  /** No results: shows "Clear filters", which calls this. */
  onClearFilters?: () => void
  compact?: boolean
}

export function EmptyState({ title, body, icon, action, onClearFilters, compact }: EmptyStateProps): JSX.Element {
  const shownIcon: IconName = icon ?? (onClearFilters ? 'search' : 'file')
  return (
    <div className={[styles.root, compact ? styles.compact : ''].join(' ')}>
      <span className={styles.icon} aria-hidden="true">
        <Icon name={shownIcon} size={compact ? 20 : 24} />
      </span>
      <p className={styles.title}>{title}</p>
      {body && <p className={styles.body}>{body}</p>}
      {(action || onClearFilters) && (
        <div className={styles.actions}>
          {onClearFilters && (
            <Button variant="secondary" size="sm" mutates={false} onClick={onClearFilters}>
              Clear filters
            </Button>
          )}
          {action &&
            ('to' in action ? (
              <Link to={action.to} className={styles.link}>
                {action.label}
              </Link>
            ) : (
              <Button variant="primary" size="sm" onClick={action.onClick}>
                {action.label}
              </Button>
            ))}
        </div>
      )}
    </div>
  )
}
