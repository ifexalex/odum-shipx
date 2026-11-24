/**
 * ErrorState (FD-20): something could not be loaded. A plain-language message (never the server's system text —
 * `ApiError.message` is already plain, see `plainErrorMessage`), a Retry, and the request reference in small text for
 * support.
 *
 *   if (error) return <ErrorState title="Couldn't load this invoice" error={error} onRetry={refetch} />
 */
import type { JSX } from 'react'
import { ApiError } from '../../api/client'
import { Button } from './Button'
import { Icon } from './Icon'
import styles from './ErrorState.module.css'

export interface ErrorStateProps {
  title: string
  error: unknown
  /** Words to use when there is no error object (a record that came back empty). */
  message?: string
  onRetry?: () => void
  compact?: boolean
}

export function ErrorState({ title, error, message: fallback, onRetry, compact }: ErrorStateProps): JSX.Element {
  const message =
    error instanceof ApiError
      ? error.message
      : (fallback ?? "Something went wrong while loading. Check your connection and try again.")
  const reference = error instanceof ApiError ? error.requestId : null
  return (
    <div className={[styles.root, compact ? styles.compact : ''].join(' ')} role="alert">
      <span className={styles.icon} aria-hidden="true">
        <Icon name="alert" size={22} />
      </span>
      <p className={styles.title}>{title}</p>
      <p className={styles.body}>{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" icon="refresh" mutates={false} onClick={onRetry}>
          Try again
        </Button>
      )}
      {reference && <p className={styles.reference}>Reference: {reference}</p>}
    </div>
  )
}
